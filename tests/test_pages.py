import pytest

PAGES = ["/", "/create", "/employees", "/profile", "/logs", "/users", "/health"]


@pytest.mark.parametrize("path", PAGES)
def test_pages_render_for_admin(as_user, path):
    r = as_user("admin").get(path)
    assert r.status_code == 200, path


def test_create_page_lists_departments_from_server(as_user):
    html = as_user("hr_a").get("/create").get_data(as_text=True)
    assert "<option>Офис</option>" in html and "<option>Колл Центр</option>" in html


def test_admin_cards_hidden_from_hr(as_user):
    assert 'href="/users"' in as_user("admin").get("/").get_data(as_text=True)
    assert 'href="/users"' not in as_user("hr_a").get("/").get_data(as_text=True)


def test_404_page_for_browser_requests(client):
    r = client.get("/no-such-page")
    assert r.status_code == 404 and "404" in r.get_data(as_text=True)
