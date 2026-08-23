import sys
from pathlib import Path
from textwrap import dedent

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from release_note_generator import DataType, parse_change_log, print_change_log


def parse(diff):
    return parse_change_log(dedent(diff).lstrip())


def test_tracks_added_removed_and_updated_datatypes():
    change_log = parse(
        """
        diff --git a/files.stone b/files.stone
        index 1111111..2222222 100644
        --- a/files.stone
        +++ b/files.stone
        @@ -1,7 +1,9 @@
         namespace files
         route existing_route(ExistingArg, ExistingResult, ExistingError)
        +route added_route(AddedArg, AddedResult, AddedError)
        -route removed_route(RemovedArg, RemovedResult, RemovedError)
         struct User
        -    old_field String
        +    new_field String
         struct ExistingStruct
        +struct AddedStruct
        -struct RemovedStruct
         union ExistingUnion
        +union AddedUnion
        -union RemovedUnion
        """
    )

    assert len(change_log.ns_changes) == 1

    ns_change = change_log.ns_changes[0]

    assert ns_change.file_name == "files"
    assert ns_change.added_routes == ["added_route"]
    assert ns_change.removed_routes == ["removed_route"]

    assert ns_change.added_structs == ["AddedStruct"]
    assert ns_change.removed_structs == ["RemovedStruct"]

    assert ns_change.added_unions == ["AddedUnion"]
    assert ns_change.removed_unions == ["RemovedUnion"]

    assert (DataType.STRUCT, "User") in ns_change.updated_datatypes


def test_tracks_plain_route_deprecation():
    change_log = parse(
        """
        diff --git a/files.stone b/files.stone
        index 1111111..2222222 100644
        --- a/files.stone
        +++ b/files.stone
        @@ -1,3 +1,3 @@
         namespace files
        -route create_folder(CreateFolderArg, FolderMetadata, CreateFolderError)
        +route create_folder(CreateFolderArg, FolderMetadata, CreateFolderError) deprecated
         route list_folder(ListFolderArg, ListFolderResult, ListFolderError)
        """
    )

    ns_change = change_log.ns_changes[0]

    assert ns_change.added_routes == []
    assert ns_change.removed_routes == []
    assert ns_change.deprecated_routes == ["create_folder"]


def test_tracks_replacement_route_deprecation():
    change_log = parse(
        """
        diff --git a/files.stone b/files.stone
        index 1111111..2222222 100644
        --- a/files.stone
        +++ b/files.stone
        @@ -1,3 +1,3 @@
         namespace files
        -route get_shared_links(GetSharedLinksArg, GetSharedLinksResult, GetSharedLinksError)
        +route get_shared_links(GetSharedLinksArg, GetSharedLinksResult, GetSharedLinksError) deprecated by list_shared_links
         route list_shared_links(ListSharedLinksArg, ListSharedLinksResult, ListSharedLinksError)
        """
    )

    ns_change = change_log.ns_changes[0]

    assert ns_change.added_routes == []
    assert ns_change.removed_routes == []
    assert ns_change.deprecated_routes == [
        "get_shared_links replaced by list_shared_links"
    ]


def test_does_not_report_new_deprecated_route_as_deprecated_change():
    change_log = parse(
        """
        diff --git a/files.stone b/files.stone
        index 1111111..2222222 100644
        --- a/files.stone
        +++ b/files.stone
        @@ -1,2 +1,3 @@
         namespace files
         route existing_route(ExistingArg, ExistingResult, ExistingError)
        +route new_deprecated_route(NewArg, NewResult, NewError) deprecated
        """
    )

    ns_change = change_log.ns_changes[0]

    assert ns_change.added_routes == ["new_deprecated_route"]
    assert ns_change.deprecated_routes == []


def test_tracks_added_and_removed_namespaces():
    change_log = parse(
        """
        diff --git a/new_namespace.stone b/new_namespace.stone
        new file mode 100644
        index 0000000..1111111
        --- /dev/null
        +++ b/new_namespace.stone
        @@ -0,0 +1,2 @@
        +namespace new_namespace
        +route added_route(AddedArg, AddedResult, AddedError)
        diff --git a/old_namespace.stone b/old_namespace.stone
        deleted file mode 100644
        index 1111111..0000000
        --- a/old_namespace.stone
        +++ /dev/null
        @@ -1,2 +0,0 @@
        -namespace old_namespace
        -route removed_route(RemovedArg, RemovedResult, RemovedError)
        """
    )

    assert change_log.added_nses == ["new_namespace"]
    assert change_log.removed_nses == ["old_namespace"]


def test_print_change_log_labels_removed_namespaces_correctly(capsys):
    change_log = parse(
        """
        diff --git a/legacy.stone b/legacy.stone
        deleted file mode 100644
        index 1111111..0000000
        --- a/legacy.stone
        +++ /dev/null
        @@ -1,2 +0,0 @@
        -namespace legacy
        -route old_route(OldArg, OldResult, OldError)
        """
    )

    print_change_log(change_log)

    output = capsys.readouterr().out

    assert "Remove legacy namespace" in output
    assert "Add legacy namespace" not in output
