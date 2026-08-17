import pytest

from library.matching import (
    classify_confidence,
    match_book,
    normalize_author,
    normalize_title,
)
from library.models import CatalogBook


@pytest.fixture
def messy_catalog(db):
    books = [
        # edition pair
        CatalogBook(
            catalog_id="CAT-001",
            title="1984",
            author="George Orwell",
            alternate_titles="Nineteen Eighty-Four|Nineteen Eighty Four",
            ambiguity_tag="edition_pair",
        ),
        CatalogBook(
            catalog_id="CAT-002",
            title="1984",
            author="George Orwell",
            alternate_titles="Nineteen Eighty-Four|Nineteen Eighty Four",
            edition_notes="Penguin hardcover",
            ambiguity_tag="edition_pair",
        ),
        # US/UK
        CatalogBook(
            catalog_id="CAT-005",
            title="Harry Potter and the Sorcerer's Stone",
            author="J.K. Rowling",
            alternate_titles="Harry Potter and the Philosopher's Stone|Sorcerer's Stone",
            ambiguity_tag="us_uk_title",
        ),
        CatalogBook(
            catalog_id="CAT-006",
            title="Harry Potter and the Philosopher's Stone",
            author="J. K. Rowling",
            alternate_titles="Harry Potter and the Sorcerer's Stone|Philosopher's Stone",
            ambiguity_tag="us_uk_title",
        ),
        # shared title, different books
        CatalogBook(
            catalog_id="CAT-015",
            title="The Road",
            author="Cormac McCarthy",
            ambiguity_tag="shared_title",
        ),
        CatalogBook(
            catalog_id="CAT-016",
            title="The Road",
            author="Jack London",
            ambiguity_tag="shared_title",
        ),
        CatalogBook(
            catalog_id="CAT-073",
            title="Inferno",
            author="Dan Brown",
            ambiguity_tag="shared_title",
        ),
        CatalogBook(
            catalog_id="CAT-074",
            title="Inferno",
            author="Dante Alighieri",
            alternate_titles="The Inferno|Inferno (Divine Comedy)",
            ambiguity_tag="shared_title",
        ),
        # omnibus vs volume
        CatalogBook(
            catalog_id="CAT-021",
            title="The Lord of the Rings",
            author="J.R.R. Tolkien",
            alternate_titles="Lord of the Rings|LOTR",
            ambiguity_tag="omnibus",
        ),
        CatalogBook(
            catalog_id="CAT-022",
            title="The Fellowship of the Ring",
            author="J.R.R. Tolkien",
            alternate_titles="Fellowship of the Ring|LOTR Book 1",
            ambiguity_tag="omnibus",
        ),
        # substring traps
        CatalogBook(
            catalog_id="CAT-032",
            title="It",
            author="Stephen King",
            ambiguity_tag="substring",
        ),
        CatalogBook(
            catalog_id="CAT-033",
            title="It Can't Happen Here",
            author="Sinclair Lewis",
            ambiguity_tag="substring",
        ),
        CatalogBook(
            catalog_id="CAT-036",
            title="Dune",
            author="Frank Herbert",
            ambiguity_tag="substring",
        ),
        CatalogBook(
            catalog_id="CAT-037",
            title="Dune Messiah",
            author="Frank Herbert",
            ambiguity_tag="substring",
        ),
        # author variants
        CatalogBook(
            catalog_id="CAT-042",
            title="One Hundred Years of Solitude",
            author="Gabriel García Márquez",
            alternate_titles="Cien años de soledad|100 Years of Solitude",
            ambiguity_tag="author_variant",
        ),
        CatalogBook(
            catalog_id="CAT-044",
            title="Love in the Time of Cholera",
            author="García Márquez, Gabriel",
            ambiguity_tag="author_variant",
        ),
        CatalogBook(
            catalog_id="CAT-045",
            title="Crime and Punishment",
            author="Fyodor Dostoevsky",
            alternate_titles="Prestuplenie i nakazanie|Crime & Punishment",
            ambiguity_tag="author_variant",
        ),
        CatalogBook(
            catalog_id="CAT-046",
            title="Crime and Punishment",
            author="Fedor Dostoevskii",
            ambiguity_tag="author_variant",
        ),
    ]
    CatalogBook.objects.bulk_create(books)
    return list(CatalogBook.objects.all())


@pytest.mark.django_db
def test_normalize_title_strips_articles_and_punct():
    assert normalize_title("The Great Gatsby!") == "great gatsby"
    assert normalize_title("Pride & Prejudice") == "pride and prejudice"


@pytest.mark.django_db
def test_normalize_author_handles_lastname_first_and_initials():
    assert normalize_author("García Márquez, Gabriel") == "gabriel garcia marquez"
    assert normalize_author("J.K. Rowling") == normalize_author("J K Rowling")
    assert normalize_author("J.K. Rowling") == normalize_author("JK Rowling")


@pytest.mark.django_db
def test_us_uk_title_matches_via_alternate(messy_catalog):
    results = match_book(
        "Harry Potter and the Philosopher's Stone",
        "J.K. Rowling",
        catalog=messy_catalog,
    )
    assert results
    top = results[0]
    assert top.catalog_id in {"CAT-005", "CAT-006"}
    assert top.confidence >= 0.82
    assert classify_confidence(top.confidence) == "high"


@pytest.mark.django_db
def test_shared_title_disambiguated_by_author(messy_catalog):
    road = match_book("The Road", "Cormac McCarthy", catalog=messy_catalog)[0]
    assert road.catalog_id == "CAT-015"
    assert road.confidence > match_book("The Road", "Jack London", catalog=messy_catalog)[0].confidence - 0.01

    london = match_book("The Road", "Jack London", catalog=messy_catalog)[0]
    assert london.catalog_id == "CAT-016"

    dante = match_book("Inferno", "Dante Alighieri", catalog=messy_catalog)[0]
    assert dante.catalog_id == "CAT-074"


@pytest.mark.django_db
def test_substring_short_title_does_not_steal_longer(messy_catalog):
    it_match = match_book("It", "Stephen King", catalog=messy_catalog)[0]
    assert it_match.catalog_id == "CAT-032"

    longer = match_book("It Can't Happen Here", "Sinclair Lewis", catalog=messy_catalog)[0]
    assert longer.catalog_id == "CAT-033"

    dune = match_book("Dune", "Frank Herbert", catalog=messy_catalog)[0]
    assert dune.catalog_id == "CAT-036"
    messiah = match_book("Dune Messiah", "Frank Herbert", catalog=messy_catalog)[0]
    assert messiah.catalog_id == "CAT-037"


@pytest.mark.django_db
def test_author_accent_and_transliteration(messy_catalog):
    # Unaccented OCR against accented catalog author
    solitude = match_book(
        "One Hundred Years of Solitude",
        "Gabriel Garcia Marquez",
        catalog=messy_catalog,
    )[0]
    assert solitude.catalog_id == "CAT-042"
    assert solitude.confidence >= 0.8

    crime = match_book(
        "Crime and Punishment",
        "Fyodor Dostoevsky",
        catalog=messy_catalog,
    )[0]
    assert crime.catalog_id in {"CAT-045", "CAT-046"}
    assert crime.confidence >= 0.75


@pytest.mark.django_db
def test_lastname_firstname_author_order(messy_catalog):
    result = match_book(
        "Love in the Time of Cholera",
        "Gabriel Garcia Marquez",
        catalog=messy_catalog,
    )[0]
    assert result.catalog_id == "CAT-044"
    assert result.confidence >= 0.8


@pytest.mark.django_db
def test_omnibus_vs_individual_volume(messy_catalog):
    fellowship = match_book(
        "The Fellowship of the Ring",
        "J.R.R. Tolkien",
        catalog=messy_catalog,
    )[0]
    assert fellowship.catalog_id == "CAT-022"

    omnibus = match_book("The Lord of the Rings", "J.R.R. Tolkien", catalog=messy_catalog)[0]
    assert omnibus.catalog_id == "CAT-021"


@pytest.mark.django_db
def test_edition_pair_both_score_high(messy_catalog):
    results = match_book("Nineteen Eighty-Four", "George Orwell", catalog=messy_catalog, limit=3)
    ids = {r.catalog_id for r in results[:2]}
    assert "CAT-001" in ids
    assert "CAT-002" in ids
    assert results[0].confidence >= 0.8


@pytest.mark.django_db
def test_low_confidence_and_unmatched(messy_catalog):
    weak = match_book("Completely Unknown Tome", "Nobody Famous", catalog=messy_catalog)[0]
    assert classify_confidence(weak.confidence) == "unmatched"

    # Title-ish but wrong author -> should not be silent high confidence
    ambiguous = match_book("The Road", "Unknown Author", catalog=messy_catalog)[0]
    assert classify_confidence(ambiguous.confidence) in {"low", "unmatched"}


@pytest.mark.django_db
def test_empty_query_returns_no_candidates(messy_catalog):
    assert match_book("", "", catalog=messy_catalog) == []
