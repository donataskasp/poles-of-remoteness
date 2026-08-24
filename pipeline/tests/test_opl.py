from poles.opl import decode, parse_members, parse_tags


def test_decode_percent_escapes():
    assert decode("Bosnia%20%and%20%Herzegovina") == "Bosnia and Herzegovina"
    assert decode("a%2c%b%3d%c%25%") == "a,b=c%"
    assert decode("plain-text_ok") == "plain-text_ok"


def test_parse_tags_and_members():
    assert parse_tags("admin_level=2,boundary=administrative,ISO3166-1=LT,name=Lietuva") == {
        "admin_level": "2", "boundary": "administrative", "ISO3166-1": "LT", "name": "Lietuva"}
    assert parse_tags("") == {}
    assert parse_members("w1@outer,w22@inner,n3@admin_centre,r4@") == [
        ("w", 1, "outer"), ("w", 22, "inner"), ("n", 3, "admin_centre"), ("r", 4, "")]
    assert parse_members("") == []
