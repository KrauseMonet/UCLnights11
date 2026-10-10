"""The Wikipedia squad parser, on hand-written wikitext in each layout it reads."""

from etl.squads import is_season_article, listed_players, name_link, position_of


def links(text):
    return {p.link: p for p in listed_players(text)}


def test_fs_player_template_reads_name_position_and_nation():
    text = """==First-team squad==
{{Fs start}}
{{fs player|no=1|nat=BRA|pos=GK|name=[[Dida (footballer, born 1973)|Dida]]}}
{{fs player|no=3|nat=ITA|pos=DF|name=[[Paolo Maldini]]}}
{{Fs end}}"""
    got = links(text)
    assert got["Dida (footballer, born 1973)"].position == "GK"
    assert got["Paolo Maldini"].nation == "ITA"


def test_a_player_loaned_out_is_not_in_the_squad():
    text = """==Squad==
{{fs player|no=18|nat=ITA|pos=FW|name=[[Nicola Pozzi]]|other=on loan to [[S.S.C. Napoli|Napoli]]}}
{{fs player|no=9|nat=UKR|pos=FW|name=[[Andriy Shevchenko]]}}"""
    assert set(links(text)) == {"Andriy Shevchenko"}


def test_reserve_youth_and_transfer_sections_are_skipped():
    text = """==Squad==
{{fs player|no=9|nat=UKR|pos=FW|name=[[Andriy Shevchenko]]}}
===Reserve squad===
{{fs player|no=40|nat=ITA|pos=GK|name=[[Reserve Keeper]]}}
==Transfers==
===In===
{{fs player|no=31|nat=NED|pos=DF|name=[[Jaap Stam]]}}"""
    assert set(links(text)) == {"Andriy Shevchenko"}


def test_fb_si_player_with_sortname_resolves_the_linked_article():
    text = """==Squad==
{{fb si player |p={{sortname||Nacho|Nacho (footballer, born 1990)}} |nb=ESP |n=6 |pos=CB}}
{{fb si player |p={{sortname|Cristiano|Ronaldo}} |nb=POR |n=7 |pos=LW}}"""
    got = links(text)
    assert got["Nacho (footballer, born 1990)"].position == "DF"
    assert got["Cristiano Ronaldo"].position == "FW"


def test_squad_statistics_row_with_attributes_and_a_captain_link():
    # The shape that hid Roy Keane: an attribute block before the name cell and a
    # second link, to the captaincy, after it.
    text = """==Squad statistics==
{| class="wikitable"
|-
!No.!!Pos.!!Name
|-
|16||MF||align="left"|{{flagicon|IRL}} [[Roy Keane]] ([[Captain (association football)|c]])
|33(2)||2
|-
|1||GK||align="left"|{{flagicon|DEN}} [[Peter Schmeichel]]
|34||0
|}"""
    got = links(text)
    assert got["Roy Keane"].position == "MF"
    assert got["Roy Keane"].nation == "IRL"
    assert "Captain (association football)" not in got


def test_position_group_rows_set_the_position_of_rows_beneath():
    text = """==Squad==
{| class="wikitable"
|-
! colspan="3"| Goalkeepers
|-
|'''1'''||[[Manuel Neuer]]||[[File:Flag of Germany.svg|20px|German]]
|-
! colspan="3"| Defenders
|-
|'''4'''||[[Dante (footballer)|Dante]]||[[File:Flag of Brazil.svg|20px]]
|}"""
    got = links(text)
    assert got["Manuel Neuer"].position == "GK"
    assert got["Dante (footballer)"].position == "DF"
    assert got["Dante (footballer)"].nation == "Brazil"


def test_position_cells():
    assert position_of("DF") == "DF"
    assert position_of("[[Goalkeeper (association football)|GK]]") == "GK"
    assert position_of("GK (R)") == "GK"
    assert position_of('align="left"|MF') == "MF"
    assert position_of("{{sort|4|FW}}") == "FW"
    assert position_of("Sergio Ramos") is None


def test_name_link_ignores_files():
    assert name_link("[[File:Yellow card.svg|13px]] [[Xabi Alonso]]") == "Xabi Alonso"
    assert name_link("plain text") is None


def test_a_redirect_to_the_club_article_is_not_a_season():
    # "1996-97 AFC Ajax season" redirects to "AFC Ajax", whose squad is today's.
    assert is_season_article("1996–97 AFC Ajax season", "1996–97")
    assert not is_season_article("AFC Ajax", "1996–97")
    assert not is_season_article("1997–98 AFC Ajax season", "1996–97")
