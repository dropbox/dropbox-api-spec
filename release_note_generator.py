import os
import re
import subprocess
from collections import defaultdict
from datetime import date
from enum import Enum
from sys import argv
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple

from unidiff import PatchSet


class DataType(str, Enum):
    ROUTE = "route"
    STRUCT = "struct"
    UNION = "union"


class RouteInfo(NamedTuple):
    name: str
    deprecated: bool
    deprecated_by: Optional[str]


class NsChange(NamedTuple):
    file_name: str
    added_routes: List[str]
    added_structs: List[str]
    added_unions: List[str]
    deprecated_routes: List[str]
    removed_routes: List[str]
    removed_structs: List[str]
    removed_unions: List[str]
    updated_datatypes: List[Tuple[DataType, str]]


class ChangeLog(NamedTuple):
    ns_changes: List[NsChange]
    added_nses: List[str]
    removed_nses: List[str]


ROUTE_RE = re.compile(
    r"^route\s+"
    r"(?P<name>[^\s(]+)"
    r"\s*\([^)]*\)"
    r"(?:\s+deprecated(?:\s+by\s+(?P<deprecated_by>[^\s]+))?)?"
    r"\s*$"
)
STRUCT_RE = re.compile(r"^struct\s+(?P<name>[^\s]+).*$")
UNION_RE = re.compile(r"^union\s+(?P<name>[^\s]+).*$")


def parse_route_info(line):
    # type: (str) -> Optional[RouteInfo]
    match = ROUTE_RE.match(line.strip())
    if not match:
        return None

    return RouteInfo(
        name=match.group("name"),
        deprecated="deprecated" in line,
        deprecated_by=match.group("deprecated_by"),
    )


def format_deprecated_route(route_info):
    # type: (RouteInfo) -> str
    if route_info.deprecated_by:
        return "{} replaced by {}".format(route_info.name, route_info.deprecated_by)

    return route_info.name


def parse_datatype_info(line):
    # type: (str) -> Optional[Tuple[DataType, str]]
    stripped_line = line.strip()

    route = parse_route_info(stripped_line)
    if route:
        return DataType.ROUTE, route.name

    struct = STRUCT_RE.match(stripped_line)
    if struct:
        return DataType.STRUCT, struct.group("name")

    union = UNION_RE.match(stripped_line)
    if union:
        return DataType.UNION, union.group("name")

    return None


def append_unique(values, value):
    # type: (List[str], str) -> None
    if value not in values:
        values.append(value)


def append_unique_datatype(values, value):
    # type: (List[Tuple[DataType, str]], Tuple[DataType, str]) -> None
    if value not in values:
        values.append(value)


def route_deprecation_changes(removed_routes, added_routes):
    # type: (Dict[str, List[RouteInfo]], Dict[str, List[RouteInfo]]) -> List[str]
    deprecated_routes = []

    for route_name, added_infos in added_routes.items():
        removed_infos = removed_routes.get(route_name, [])
        if not removed_infos:
            continue

        was_deprecated = any(route.deprecated for route in removed_infos)

        for added_info in added_infos:
            if added_info.deprecated and not was_deprecated:
                append_unique(deprecated_routes, format_deprecated_route(added_info))

    return deprecated_routes


def parse_change_log(change_log_diff):
    # type: (str) -> ChangeLog
    ns_changes = []
    added_nses = []
    removed_nses = []

    patch = PatchSet(change_log_diff)

    for patch_file in patch:
        path_parts = os.path.basename(patch_file.path).split(".")
        if len(path_parts) != 2:
            continue

        ns_file_name, ext = path_parts

        if ext != "stone":
            continue

        if patch_file.is_added_file:
            added_nses.append(ns_file_name)
            continue

        if patch_file.is_removed_file:
            removed_nses.append(ns_file_name)
            continue

        added_routes = []
        added_structs = []
        added_unions = []
        deprecated_routes = []
        removed_routes = []
        removed_structs = []
        removed_unions = []
        updated_datatypes = []

        route_map = defaultdict(int)
        added_route_infos = defaultdict(list)
        removed_route_infos = defaultdict(list)

        # Pass for checking creation, deletion, and route deprecation changes.
        for hunk in patch_file:
            for line in hunk:
                datatype_info = parse_datatype_info(line.value)
                if datatype_info is None:
                    continue

                datatype, datatype_name = datatype_info

                if datatype == DataType.ROUTE:
                    route_info = parse_route_info(line.value)
                    if route_info is None:
                        continue

                    if line.is_added:
                        route_map[datatype_name] += 1
                        added_route_infos[datatype_name].append(route_info)

                    if line.is_removed:
                        route_map[datatype_name] -= 1
                        removed_route_infos[datatype_name].append(route_info)

                if datatype == DataType.STRUCT:
                    if line.is_added:
                        append_unique(added_structs, datatype_name)

                    if line.is_removed:
                        append_unique(removed_structs, datatype_name)

                if datatype == DataType.UNION:
                    if line.is_added:
                        append_unique(added_unions, datatype_name)

                    if line.is_removed:
                        append_unique(removed_unions, datatype_name)

            datatype = None
            datatype_name = None
            seen_datatypes = set()

            # Pass to check for updated datatypes.
            for line in hunk:
                datatype_info = parse_datatype_info(line.value)

                if datatype_info and not line.is_removed:
                    if line.is_added:
                        datatype = None
                        datatype_name = None
                    else:
                        datatype, datatype_name = datatype_info

                if not datatype_info and datatype and datatype_name:
                    if (line.is_removed or line.is_added) and datatype_name not in seen_datatypes:
                        append_unique_datatype(updated_datatypes, (datatype, datatype_name))
                        seen_datatypes.add(datatype_name)

        deprecated_routes.extend(
            route_deprecation_changes(removed_route_infos, added_route_infos)
        )

        for route, ref_count in route_map.items():
            if ref_count > 0:
                append_unique(added_routes, route)

            if ref_count < 0:
                append_unique(removed_routes, route)

        # Do not report a brand-new deprecated route as both added and deprecated.
        deprecated_routes = [
            route
            for route in deprecated_routes
            if route.split(" replaced by ", 1)[0] not in added_routes
        ]

        ns_change = NsChange(
            ns_file_name,
            added_routes,
            added_structs,
            added_unions,
            deprecated_routes,
            removed_routes,
            removed_structs,
            removed_unions,
            updated_datatypes,
        )
        ns_changes.append(ns_change)

    return ChangeLog(ns_changes, added_nses, removed_nses)


def read_diff(args):
    # type: (Iterable[str]) -> str
    args = list(args)

    if args:
        with open(args[0], "r") as diff_file:
            return diff_file.read()

    return subprocess.check_output(["git", "diff"]).decode("utf-8")


def pluralize(noun, count):
    # type: (str, int) -> str
    if count == 1:
        return noun

    return "{}s".format(noun)


def print_list_change(action, values, noun):
    # type: (str, List[str], str) -> None
    if values:
        print(
            "- {} {} {}".format(
                action,
                ", ".join(values),
                pluralize(noun, len(values)),
            )
        )


def print_change_log(change_log):
    # type: (ChangeLog) -> None
    print("Spec Update {} (#<TODO>)".format(date.today().strftime("%m/%d/%Y")))
    print()
    print("Change Notes:")

    for ns_change in change_log.ns_changes:
        print()
        print("{} Namespace".format(ns_change.file_name))

        print_list_change("Add", ns_change.added_routes, "route")
        print_list_change("Add", ns_change.added_structs, "struct")
        print_list_change("Add", ns_change.added_unions, "union")
        print_list_change("Deprecate", ns_change.deprecated_routes, "route")
        print_list_change("Remove", ns_change.removed_routes, "route")
        print_list_change("Remove", ns_change.removed_structs, "struct")
        print_list_change("Remove", ns_change.removed_unions, "union")

        for datatype, datatype_name in ns_change.updated_datatypes:
            print(
                "- Update {} {} to include/remove/deprecate <TODO>".format(
                    datatype_name,
                    datatype.value,
                )
            )

    if change_log.added_nses:
        print()
        for ns in change_log.added_nses:
            print("Add {} namespace".format(ns))

    if change_log.removed_nses:
        print()
        for ns in change_log.removed_nses:
            print("Remove {} namespace".format(ns))


def main():
    diff = read_diff(argv[1:])
    change_log = parse_change_log(diff)
    print_change_log(change_log)


if __name__ == "__main__":
    main()
