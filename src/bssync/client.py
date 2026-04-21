"""BookStack API client.

Single class that encapsulates all HTTP interaction with a BookStack
instance. Caches books and chapters to reduce redundant API calls during
a single run. All methods raise BookStackAPIError on HTTP errors — they
never print to stdout, so the client is safe to use from the MCP server
where stdout is the protocol channel.
"""

import mimetypes
from pathlib import Path
from typing import Optional

import requests


class BookStackAPIError(RuntimeError):
    """Raised when a BookStack API call returns a non-2xx response.

    Carries the status code, method, and URL so callers can render a
    useful error message without having to parse str(e).
    """
    def __init__(self, method: str, url: str, status: int, body: str = ""):
        self.method = method
        self.url = url
        self.status = status
        self.body = body
        detail = f": {body[:200]}" if body else ""
        super().__init__(f"{method} {url} -> {status}{detail}")


class BookStackClient:
    """Thin wrapper over the BookStack HTTP API.

    Instantiate with a base URL and token credentials, then call the
    domain methods (`list_books`, `create_page`, `upload_image`, etc.).
    All methods return plain dicts decoded from the JSON response.
    """

    def __init__(self, url: str, token_id: str, token_secret: str,
                 dry_run: bool = False, verbose: bool = False):
        self.url = url.rstrip("/")
        self.token_id = token_id
        self.token_secret = token_secret
        self.headers = {
            "Authorization": f"Token {token_id}:{token_secret}",
            "Content-Type": "application/json",
        }
        self.dry_run = dry_run
        self.verbose = verbose

        # Caches to avoid repeated API calls within a single run
        self._books_cache: Optional[list] = None
        self._chapters_cache: dict[int, list] = {}

    # ─── Low-level HTTP ───

    def _log(self, msg: str):
        if self.verbose:
            print(f"  [api] {msg}")

    def _request(self, method: str, path: str, data: dict = None) -> dict:
        url = f"{self.url}/api/{path.lstrip('/')}"
        self._log(f"{method} {url}")
        resp = requests.request(method, url, headers=self.headers,
                                json=data, timeout=30)
        if resp.status_code >= 400:
            raise BookStackAPIError(method, url, resp.status_code, resp.text)
        return resp.json() if resp.text else {}

    def _request_multipart(self, method: str, path: str,
                           data: dict, files: dict) -> dict:
        """Send a multipart/form-data request (for file uploads)."""
        url = f"{self.url}/api/{path.lstrip('/')}"
        self._log(f"{method} {url} (multipart)")
        headers = {"Authorization": f"Token {self.token_id}:{self.token_secret}"}
        resp = requests.request(method, url, headers=headers,
                                data=data, files=files, timeout=60)
        if resp.status_code >= 400:
            raise BookStackAPIError(method, url, resp.status_code, resp.text)
        return resp.json() if resp.text else {}

    def _get_all(self, path: str) -> list:
        """Fetch all items from a paginated BookStack endpoint."""
        items = []
        offset = 0
        while True:
            resp = self._request("GET", f"{path}?count=100&offset={offset}")
            data = resp.get("data", [])
            items.extend(data)
            if len(data) < 100:
                break
            offset += 100
        return items

    # ─── Books ───

    def list_books(self) -> list:
        if self._books_cache is None:
            self._books_cache = self._get_all("books")
        return self._books_cache

    def find_book(self, name: str) -> Optional[dict]:
        for book in self.list_books():
            if book["name"].lower() == name.lower():
                return book
        return None

    def create_book(self, name: str, description: str = "") -> dict:
        if self.dry_run:
            return {"id": -1, "name": name, "_dry_run": True}
        self._log(f"Creating book: {name}")
        book = self._request("POST", "books",
                             {"name": name, "description": description})
        self._books_cache = None  # invalidate
        return book

    # ─── Chapters ───

    def list_chapters(self, book_id: int) -> list:
        if book_id not in self._chapters_cache:
            self._chapters_cache[book_id] = [
                ch for ch in self._get_all("chapters")
                if ch.get("book_id") == book_id
            ]
        return self._chapters_cache[book_id]

    def find_chapter(self, book_id: int, name: str) -> Optional[dict]:
        for ch in self.list_chapters(book_id):
            if ch["name"].lower() == name.lower():
                return ch
        return None

    def create_chapter(self, book_id: int, name: str,
                       description: str = "") -> dict:
        if self.dry_run:
            return {"id": -1, "name": name, "book_id": book_id,
                    "_dry_run": True}
        self._log(f"Creating chapter: {name} in book {book_id}")
        ch = self._request("POST", "chapters", {
            "book_id": book_id, "name": name, "description": description,
        })
        self._chapters_cache.pop(book_id, None)  # invalidate
        return ch

    # ─── Pages ───

    def list_pages(self) -> list:
        """List all pages across all books."""
        return self._get_all("pages")

    def find_page_in_book(self, book_id: int, name: str) -> Optional[dict]:
        """Search for a page by name within a specific book."""
        results = self._request(
            "GET", f"search?query={requests.utils.quote(name)}&type=page&count=50"
        )
        for item in results.get("data", []):
            if (item.get("name", "").lower() == name.lower()
                    and item.get("book_id") == book_id):
                return item
        return None

    def get_page(self, page_id: int) -> dict:
        return self._request("GET", f"pages/{page_id}")

    def search(self, query: str, type: str = "page", count: int = 20) -> list:
        """Full-text search. Returns raw search hits (with book_id,
        chapter_id, url, preview_html, etc.).
        """
        q = requests.utils.quote(query)
        resp = self._request("GET",
                             f"search?query={q}&type={type}&count={count}")
        return resp.get("data", [])

    def create_page(self, name: str, markdown: str,
                    book_id: int = None, chapter_id: int = None,
                    tags: list = None) -> dict:
        if self.dry_run:
            return {"id": -1, "name": name, "_dry_run": True}
        payload = {"name": name, "markdown": markdown}
        if chapter_id:
            payload["chapter_id"] = chapter_id
        elif book_id:
            payload["book_id"] = book_id
        if tags:
            payload["tags"] = tags
        return self._request("POST", "pages", payload)

    def update_page(self, page_id: int, name: str, markdown: str,
                    tags: list = None,
                    chapter_id: int = None,
                    book_id: int = None) -> dict:
        """Update a page. Pass chapter_id to move into a chapter, or book_id
        (with chapter_id unset) to move to the book root. Omit both to leave
        the page's location unchanged.
        """
        if self.dry_run:
            return {"id": page_id, "name": name, "_dry_run": True}
        payload = {"name": name, "markdown": markdown}
        if tags:
            payload["tags"] = tags
        if chapter_id is not None:
            payload["chapter_id"] = chapter_id
        elif book_id is not None:
            payload["book_id"] = book_id
        return self._request("PUT", f"pages/{page_id}", payload)

    # ─── Images ───

    def upload_image(self, page_id: int, image_path: Path,
                     name: str = None) -> dict:
        """Upload an image to the page's gallery. Returns image object with url."""
        if self.dry_run:
            return {"id": -1,
                    "url": f"(dry-run:{image_path.name})",
                    "path": f"/uploads/images/gallery/dry-run/{image_path.name}",
                    "_dry_run": True}
        display_name = name or image_path.stem
        mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
        with open(image_path, "rb") as f:
            result = self._request_multipart(
                "POST", "image-gallery",
                data={"type": "gallery", "uploaded_to": str(page_id),
                      "name": display_name},
                files={"image": (image_path.name, f, mime)},
            )
        self._log(f"Uploaded image: {image_path.name} → {result.get('url')}")
        return result

    def update_image(self, image_id: int, image_path: Path,
                     name: str = None) -> dict:
        """Replace an existing gallery image's content. BookStack requires
        the same file type as the original. Image id and URL remain stable
        across the update.

        BookStack runs on Laravel, whose form-data parser does not read the
        body of PUT requests. We POST with an `_method=PUT` spoof so Laravel
        routes to the update handler while still parsing the multipart body.
        """
        if self.dry_run:
            return {"id": image_id,
                    "url": f"(dry-run:{image_path.name})",
                    "_dry_run": True}
        display_name = name or image_path.stem
        mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
        with open(image_path, "rb") as f:
            result = self._request_multipart(
                "POST", f"image-gallery/{image_id}",
                data={"_method": "PUT", "name": display_name},
                files={"image": (image_path.name, f, mime)},
            )
        self._log(f"Replaced image {image_id}: {image_path.name}")
        return result

    def list_page_images(self, page_id: int) -> list:
        """List gallery images uploaded to a specific page."""
        all_images = self._get_all("image-gallery")
        return [img for img in all_images if img.get("uploaded_to") == page_id]

    def delete_image(self, image_id: int):
        if self.dry_run:
            return
        self._request("DELETE", f"image-gallery/{image_id}")

    # ─── Attachments ───

    def upload_attachment(self, page_id: int, file_path: Path,
                          name: str = None) -> dict:
        """Upload a file attachment to a page."""
        if self.dry_run:
            return {"id": -1, "name": name or file_path.name,
                    "_dry_run": True}
        display_name = name or file_path.name
        mime = (mimetypes.guess_type(str(file_path))[0]
                or "application/octet-stream")
        with open(file_path, "rb") as f:
            result = self._request_multipart(
                "POST", "attachments",
                data={"name": display_name, "uploaded_to": str(page_id)},
                files={"file": (file_path.name, f, mime)},
            )
        self._log(f"Uploaded attachment: {file_path.name} → page {page_id}")
        return result

    def update_attachment(self, attachment_id: int, file_path: Path,
                          name: str = None) -> dict:
        """Replace an existing attachment's content. Attachment id and
        download URL remain stable across the update, so external links
        are not broken.

        BookStack runs on Laravel, whose form-data parser does not read the
        body of PUT requests. We POST with an `_method=PUT` spoof so Laravel
        routes to the update handler while still parsing the multipart body.
        """
        if self.dry_run:
            return {"id": attachment_id, "name": name or file_path.name,
                    "_dry_run": True}
        display_name = name or file_path.name
        mime = (mimetypes.guess_type(str(file_path))[0]
                or "application/octet-stream")
        with open(file_path, "rb") as f:
            result = self._request_multipart(
                "POST", f"attachments/{attachment_id}",
                data={"_method": "PUT", "name": display_name},
                files={"file": (file_path.name, f, mime)},
            )
        self._log(f"Replaced attachment {attachment_id}: {file_path.name}")
        return result

    def list_page_attachments(self, page_id: int) -> list:
        """List attachments on a page."""
        all_attachments = self._get_all("attachments")
        return [a for a in all_attachments if a.get("uploaded_to") == page_id]

    def delete_attachment(self, attachment_id: int):
        if self.dry_run:
            return
        self._request("DELETE", f"attachments/{attachment_id}")

    # ─── Health ───

    def verify_connection(self) -> bool:
        """Test that the API credentials work. Silent — callers that want
        to report the failure should catch BookStackAPIError themselves."""
        try:
            self._request("GET", "books?count=1")
            return True
        except Exception:
            return False
