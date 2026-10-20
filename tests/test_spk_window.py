from datetime import timedelta

import pypdf

from radar.config import Stock, TickerMatcher
from radar.models import now_utc
from radar.sources import Context, spk

ST = Stock("GARAN", "Garanti BBVA", "BIST", ["Türkiye Garanti Bankası"])


class R:
    def __init__(self, text="", content=b""):
        self.text, self.content = text, content


class FakePdf:
    metadata = None

    def __init__(self, _):
        self.pages = [type("P", (), {"extract_text": lambda self: "Türkiye Garanti Bankası A.Ş. ihraç belgesi onaylandı"})()]


def test_late_published_bulletin_is_not_lost(monkeypatch):
    # Bülten listede yalnız günüyle var (18:00 sayılır); radar son çalıştırmadan 2 sa öncesine bakıyor.
    # Akşam geç yayımlanan bülten bu pencereye girmediği için eskiden hiç alınmıyordu.
    day = (now_utc() - timedelta(days=1)).astimezone(spk.IST)
    months = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    old = (now_utc() - timedelta(days=40)).astimezone(spk.IST)
    html = (f'<a href="https://spk.gov.tr/data/x/{day.year}-71.pdf" class="link"><div>Bülten No : {day.year}/71</div>'
            f'<div>Yayımlanma : {day.day} {months[day.month - 1]} {day.year}</div></a>'
            f'<a href="https://spk.gov.tr/data/y/{old.year}-40.pdf" class="link"><div>Bülten No : {old.year}/40</div>'
            f'<div>Yayımlanma : {old.day} {months[old.month - 1]} {old.year}</div></a>')
    monkeypatch.setattr(spk.http, "get", lambda url, **k: R(text=html) if url.endswith("bultenleri") else R(content=b"%PDF"))
    monkeypatch.setattr(pypdf, "PdfReader", FakePdf)
    ctx = Context(settings={"sources": {}}, stocks=[ST], matcher=TickerMatcher([ST]), since=now_utc() - timedelta(hours=2), seen={"x"})
    items = spk.collect(ctx)
    assert [i.extra["bulletin"] for i in items] == [f"{day.year}/71"]       # 40 günlük eski bülten alınmaz
    assert items[0].tickers == ["GARAN"]
    ctx.seen.add(items[0].id)
    assert spk.collect(ctx) == []                                           # görülen bülten tekrar alınmaz
