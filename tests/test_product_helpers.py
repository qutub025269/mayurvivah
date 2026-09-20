import sqlite3

from app import get_product_images, product_badges, split_csv_list


def test_split_csv_list_handles_blank_values():
    assert split_csv_list("S, M, L, , XL") == ["S", "M", "L", "XL"]


def test_get_product_images_uses_primary_and_secondary_images():
    product = {
        "image": "uploads/hero.jpg",
        "images": "uploads/side1.jpg; uploads/side2.jpg; ; uploads/side3.jpg",
    }
    assert get_product_images(product) == [
        "uploads/hero.jpg",
        "uploads/side1.jpg",
        "uploads/side2.jpg",
        "uploads/side3.jpg",
    ]


def test_product_badges_include_new_and_best_seller_labels():
    product = {"is_new": 1, "featured": 1, "is_best_seller": 1}
    assert product_badges(product) == ["New", "Best Seller"]


def test_product_helpers_work_with_sqlite_rows():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT 1 AS is_new, 1 AS is_best_seller, 1 AS featured, 'uploads/a.jpg; uploads/b.jpg' AS images"
    ).fetchone()

    assert get_product_images(row) == ["uploads/a.jpg", "uploads/b.jpg"]
    assert product_badges(row) == ["New", "Best Seller"]
