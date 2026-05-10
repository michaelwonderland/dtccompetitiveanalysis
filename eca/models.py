from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class Review:
    product_url: str
    product_handle: str
    author: Optional[str] = None
    rating: Optional[float] = None
    title: Optional[str] = None
    body: Optional[str] = None
    created_at: Optional[str] = None
    verified: Optional[bool] = None
    helpful_count: Optional[int] = None
    review_id: Optional[str] = None
    raw: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        return d


CSV_FIELDS = [
    "product_url",
    "product_handle",
    "author",
    "rating",
    "title",
    "body",
    "created_at",
    "verified",
    "helpful_count",
    "review_id",
]
