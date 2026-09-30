# API Reference

HTTP API exposed by the WSGI app built in `service.app.create_app`. All
responses are JSON except the 302 redirect, which has an empty body.

## POST /shorten

Mint a short code for a long URL.

**Request body** (JSON object):

| Field | Type | Required | Notes |
|---|---|---|---|
| `long_url` | string | yes | Must be a non-empty `http://` or `https://` URL with a host. |

**Responses:**

| Status | Body | When |
|---|---|---|
| 201 Created | `{"code": "<short code>"}` | URL validated and saved. |
| 400 Bad Request | `{"error": "request body must be valid JSON"}` | Body is not parseable JSON. |
| 400 Bad Request | `{"error": "request body must be a JSON object"}` | Parsed JSON is not an object. |
| 400 Bad Request | `{"error": "long_url must be a non-empty string"}` | `long_url` missing, not a string, or empty. |
| 400 Bad Request | `{"error": "long_url must use http or https"}` | `long_url` scheme is not `http`/`https`. |
| 400 Bad Request | `{"error": "long_url must include a host"}` | `long_url` has no netloc. |

Short codes are 7 characters from `[A-Za-z0-9]`, generated with
`secrets.choice` and re-rolled on collision.

Example:

```
POST /shorten
Content-Type: application/json

{"long_url": "https://example.com/some/page"}
```

```
201 Created
Content-Type: application/json

{"code": "aZ3kLo9"}
```

## GET /{code}

Redirect to the long URL a code was minted for.

**Responses:**

| Status | Body | Headers | When |
|---|---|---|---|
| 302 Found | *(empty)* | `Location: <long_url>` | `code` is a known short code. |
| 404 Not Found | `{"error": "code not found"}` | — | `code` is unknown. |

Example:

```
GET /aZ3kLo9
```

```
302 Found
Location: https://example.com/some/page
Content-Length: 0
```

## Unmatched routes

Any request that doesn't match `POST /shorten` or `GET /{code}` (including
`GET /` and `GET ""`) returns:

```
404 Not Found
Content-Type: application/json

{"error": "not found"}
```
