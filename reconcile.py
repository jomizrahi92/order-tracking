#!/usr/bin/env python3

import argparse
from typing import Dict, Tuple

from lib import clusters
from tqdm import tqdm
from lib.cancelled_items_retriever import CancelledItemsRetriever
from lib.config import open_config
from lib.non_portal_reimbursements import NonPortalReimbursements
from lib.order_info import OrderInfoRetriever
from lib.group_site_manager import GroupSiteManager
from lib.driver_creator import DriverCreator
from lib.reconciliation_uploader import ReconciliationUploader
from lib.tracking_output import TrackingOutput


def fill_costs(tqdm_msg: str, all_clusters, config, fetch_from_email: bool):
  order_info_retriever = OrderInfoRetriever(config)
  total_orders = sum([len(cluster.orders) for cluster in all_clusters])
  with tqdm(desc=tqdm_msg, unit='order', total=total_orders) as pbar:
    for cluster in all_clusters:
      cluster.expected_cost = 0.0
      cluster.email_ids = set()
      for order_id in cluster.orders:
        try:
          order_info = order_info_retriever.get_order_info(order_id, fetch_from_email)
          cluster.expected_cost += order_info.cost
          if order_info.email_id:
            # Only add the email ID if it's present; don't add Nones!
            cluster.email_ids.add(order_info.email_id)
        except Exception as e:
          tqdm.write(
              f"Exception when getting order info for {order_id}. Please check the oldest email associated with that order. Skipping..."
          )
          tqdm.write(str(e))
        pbar.update()


def apply_non_portal_reimbursements(config, trackings_to_costs_map: Dict[Tuple[str], Tuple[str,
                                                                                           float]],
                                    po_to_cost_map: Dict[str, float]) -> None:
  non_portal_reimbursements = NonPortalReimbursements(config)
  duplicate_tracking_tuples = set(non_portal_reimbursements.trackings_to_costs.keys()).intersection(
      trackings_to_costs_map.keys())
  if duplicate_tracking_tuples:
    for duplicate in duplicate_tracking_tuples:
      print(
          f'Tracking {duplicate} in non-portal reimbursements also group {trackings_to_costs_map[duplicate][0]}'
      )
    raise Exception('Non-reimbursed trackings should not be duplicated in a portal')

  duplicate_pos = set(non_portal_reimbursements.po_to_cost.keys()).intersection(
      po_to_cost_map.keys())
  if duplicate_pos:
    for duplicate_po in duplicate_pos:
      print(f'PO {duplicate_po} included in non-portal reimbursements but also found in a portal')
    raise Exception('Non-reimbursed POs should not be duplicated in a portal')

  trackings_to_costs_map.update(non_portal_reimbursements.trackings_to_costs)
  po_to_cost_map.update(non_portal_reimbursements.po_to_cost)


def get_new_tracking_pos_costs_maps(
    config, group_site_manager: GroupSiteManager,
    args) -> Tuple[Dict[Tuple[str], Tuple[str, float]], Dict[str, float]]:
  print("Loading tracked costs. This will take several minutes.")
  if args.groups:
    print("Only reconciling groups %s" % ",".join(args.groups))
    groups = args.groups
  else:
    groups = config['groups'].keys()

  trackings_to_costs_map: Dict[Tuple[str], Tuple[str, float]] = {}
  po_to_cost_map: Dict[str, float] = {}
  for group in groups:
    group_trackings_to_po, group_po_to_cost = group_site_manager.get_new_tracking_pos_costs_maps_with_retry(
        group)
    trackings_to_costs_map.update({k: (
        group,
        v,
    ) for (k, v) in group_trackings_to_po.items()})
    po_to_cost_map.update(group_po_to_cost)

  apply_non_portal_reimbursements(config, trackings_to_costs_map, po_to_cost_map)
  return trackings_to_costs_map, po_to_cost_map


def map_clusters_by_tracking(all_clusters):
  result = {}
  for cluster in all_clusters:
    for tracking in cluster.trackings:
      result[tracking] = cluster
  return result


def merge_by_trackings_tuples(clusters_by_tracking, trackings_to_cost, all_clusters):
  for trackings_tuple, cost in trackings_to_cost.items():
    if len(trackings_tuple) == 1:
      continue

    cluster_list = [
        clusters_by_tracking[tracking]
        for tracking in trackings_tuple
        if tracking in clusters_by_tracking
    ]

    if not cluster_list:
      continue

    # Merge all candidate clusters into the first cluster (if they're not already part of it)
    # then set all trackings to have the first cluster as their value
    first_cluster = cluster_list[0]
    for other_cluster in cluster_list[1:]:
      if not (other_cluster.trackings.issubset(first_cluster.trackings) and
              other_cluster.orders.issubset(first_cluster.orders)):
        if other_cluster in all_clusters:
          all_clusters.remove(other_cluster)
        first_cluster.merge_with(other_cluster)
    for tracking in trackings_tuple:
      clusters_by_tracking[tracking] = first_cluster


def fill_costs_new(clusters_by_tracking, trackings_to_cost: Dict[Tuple[str], Tuple[str, float]],
                   po_to_cost: Dict[str, float], args):
  for cluster in clusters_by_tracking.values():
    # Reset the cluster if it's included in the groups
    if args.groups and cluster.group not in args.groups:
      continue
    cluster.non_reimbursed_trackings = set(cluster.trackings)
    cluster.tracked_cost = 0

  # We've already merged by tracking tuple (if multiple trackings are counted as the same price)
  # so only use the first tracking in each tuple
  for trackings_tuple, (group, cost) in trackings_to_cost.items():
    first_tracking: str = trackings_tuple[0]
    if first_tracking in clusters_by_tracking:
      cluster = clusters_by_tracking[first_tracking]
      cluster.tracked_cost += cost
      for tracking in trackings_tuple:
        if tracking in cluster.non_reimbursed_trackings:
          cluster.non_reimbursed_trackings.remove(tracking)
    elif args.print_unknowns:
      print(f"Unknown tracking for group {group}: {first_tracking}")

  # Next, manual PO fixes
  for cluster in clusters_by_tracking.values():
    pos = cluster.purchase_orders
    if pos:
      for po in pos:
        cluster.tracked_cost += float(po_to_cost.get(po, 0.0))


def fill_cancellations(all_clusters, config):
  retriever = CancelledItemsRetriever(config)
  cancellations_by_order = retriever.get_cancelled_items()

  for cluster in all_clusters:
    cluster.cancelled_items = []
    for order in cluster.orders:
      if order in cancellations_by_order:
        cluster.cancelled_items += cancellations_by_order[order]


def reconcile_new(config, args):
  reconciliation_uploader = ReconciliationUploader(config)

  tracking_output = TrackingOutput(config)
  trackings = tracking_output.get_existing_trackings()
  reconcilable_trackings = [t for t in trackings if t.reconcile]
  # start from scratch
  all_clusters = []
  clusters.update_clusters(all_clusters, reconcilable_trackings)

  fill_costs('Fetching order costs', all_clusters, config, True)
  all_clusters = clusters.merge_orders(all_clusters)
  fill_costs('Filling merged order costs', all_clusters, config, False)

  # add manual PO entries (and only manual ones)
  reconciliation_uploader.override_pos_and_costs(all_clusters)

  driver_creator = DriverCreator()
  group_site_manager = GroupSiteManager(config, driver_creator)

  trackings_to_cost, po_to_cost = get_new_tracking_pos_costs_maps(config, group_site_manager, args)

  clusters_by_tracking = map_clusters_by_tracking(all_clusters)
  merge_by_trackings_tuples(clusters_by_tracking, trackings_to_cost, all_clusters)

  fill_costs_new(clusters_by_tracking, trackings_to_cost, po_to_cost, args)

  fill_cancellations(all_clusters, config)
  reconciliation_uploader.download_upload_clusters_new(all_clusters)


def main():
  parser = argparse.ArgumentParser(description='Reconciliation script')
  parser.add_argument("--groups", nargs="*")
  parser.add_argument(
      "--print-unknowns",
      "-u",
      action="store_true",
      help="print unknown trackings found in BG portals")
  args, _ = parser.parse_known_args()
  config = open_config()

  print("Reconciling ...")
  reconcile_new(config, args)


if __name__ == "__main__":
  main()
