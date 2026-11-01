from bs4 import BeautifulSoup

from portal.models import db, Assignment


def test_compact_pagination_preserves_distinct_objects_with_same_name(app, client):
    with app.app_context():
        for index in range(25):
            db.session.add(Assignment(source_id=f'page-object-{index}', version='synthetic-only',
                region='6502000000000001', name='OBJEK SAMA', building='20',
                kind='BKU', status='OPEN', existence='Kode 1'))
        db.session.commit()
    links = []
    for page, expected in [(1, 12), (2, 12), (3, 1)]:
        response = client.get(f'/sls/6502000000000001?q=OBJEK+SAMA&page={page}')
        assert response.status_code == 200
        soup = BeautifulSoup(response.data, 'html.parser')
        cards = soup.select('.assignment-card')
        assert len(cards) == expected
        links.extend(card['href'].split('?')[0] for card in cards)
        assert f'dari 25 objek' in soup.get_text()
    assert len(set(links)) == 25
    beyond = BeautifulSoup(client.get('/sls/6502000000000001?q=OBJEK+SAMA&page=999').data, 'html.parser')
    assert len(beyond.select('.assignment-card')) == 1
