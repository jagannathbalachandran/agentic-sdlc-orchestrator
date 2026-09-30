# Plan

## FR-1: Shorten a long URL
- T-1.1 (DD-1): Add the `flask>=3.0,<4.0` runtime dependency to `pyproject.toml` and implement the application factory (`create_app`, `register_routes`) in `src/service/app.py`, binding a `URLStore` to `app.config["URL_STORE"]` with route skeletons for `POST /shorten` and `GET /<code>`. No dependencies.
- T-1.2 (DD-3): Implement short-code generation in `src/service/codes.py` (`CODE_ALPHABET`, `CODE_LENGTH`, `generate_code` using `secrets.choice`). No dependencies.
- T-1.3 (DD-3): Implement `URLStore` (`put`/`get`) in `src/service/storage.py`, calling `codes.generate_code` in a retry loop on collision. Depends on: T-1.2.
- T-1.4 (DD-2): Implement `is_valid_url` in `src/service/urls.py` (str check, http/https scheme, non-empty netloc via `urllib.parse.urlparse`). No dependencies.
- T-1.5 (DD-2): Implement the `POST /shorten` handler in `src/service/app.py` — parse JSON body, validate via `is_valid_url`, delegate to `URLStore.put`, and return the `201`/`400` response contract from DD-2. Depends on: T-1.1, T-1.3, T-1.4.

## FR-2: Redirect from a short code
- T-2.1 (DD-4): Implement the `GET /<code>` handler (`redirect_to_original`) in `src/service/app.py` — look up the code via `URLStore.get`, returning a `302` redirect with `Location` set on hit or aborting with `404` (no `Location` header) on miss. Depends on: T-1.1, T-1.3.
