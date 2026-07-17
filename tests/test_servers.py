from lib import servers


def test_deserialize_empty_string():
    assert servers.deserialize("") == []


def test_deserialize_invalid_json():
    assert servers.deserialize("not json") == []


def test_deserialize_non_list_json():
    assert servers.deserialize('{"a": 1}') == []


def test_serialize_deserialize_round_trip():
    server_list = [{"id": "s1", "name": "Tower", "server_url": "http://a:8096",
                    "access_token": "tok", "user_id": "u1"}]
    assert servers.deserialize(servers.serialize(server_list)) == server_list


def test_find_returns_match():
    server_list = [{"id": "s1", "name": "Tower"}, {"id": "s2", "name": "Attic"}]
    assert servers.find(server_list, "s2") == {"id": "s2", "name": "Attic"}


def test_find_returns_none_when_missing():
    assert servers.find([], "s1") is None


def test_upsert_adds_new_server_with_generated_id():
    new_list, server_id = servers.upsert([], {
        "name": "Tower", "server_url": "http://a:8096",
        "access_token": "tok", "user_id": "u1",
    })
    assert len(new_list) == 1
    assert new_list[0]["id"] == server_id
    assert server_id


def test_upsert_updates_existing_entry_by_url_case_insensitive():
    existing = {"id": "s1", "name": "Old Name", "server_url": "http://a:8096",
                "access_token": "old-tok", "user_id": "old-user"}
    new_list, server_id = servers.upsert([existing], {
        "name": "New Name", "server_url": "HTTP://A:8096",
        "access_token": "new-tok", "user_id": "new-user",
    })
    assert server_id == "s1"
    assert len(new_list) == 1
    assert new_list[0] == {
        "id": "s1", "name": "New Name", "server_url": "HTTP://A:8096",
        "access_token": "new-tok", "user_id": "new-user",
    }


def test_upsert_does_not_mutate_a_different_entry():
    other = {"id": "s2", "name": "Attic", "server_url": "http://b:8096",
              "access_token": "tok-b", "user_id": "user-b"}
    new_list, server_id = servers.upsert([other], {
        "name": "Tower", "server_url": "http://a:8096",
        "access_token": "tok-a", "user_id": "user-a",
    })
    assert len(new_list) == 2
    assert other in new_list
    assert server_id not in ("s2",)


def test_remove_filters_by_id():
    server_list = [{"id": "s1"}, {"id": "s2"}]
    assert servers.remove(server_list, "s1") == [{"id": "s2"}]


def test_remove_missing_id_is_noop():
    server_list = [{"id": "s1"}]
    assert servers.remove(server_list, "does-not-exist") == server_list
