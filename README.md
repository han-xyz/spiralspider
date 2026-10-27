# spiralspider

Gathers quest data for the worlds the Wizard101 data pack ([spiraldb](../spiraldb)) still lacks, from sources that
permit it, and writes a spiraltools quest spec per quest and a gap report per world. It is built on Scrapy: each
source is a Scrapy spider, and `crawl` runs them one after the other in one Scrapy process. The live wiki is read
through scrapy-playwright with a plain headless Chromium inside a disposable Docker container: no host profile, no
cookies, a fresh browser context per crawl, and no anti-detection or fingerprint changes of any kind.

## The stop rule

When a source refuses us, the spider stops asking it. A Cloudflare challenge page ("Just a moment...", "Performing
security verification", "Verify you are human", a Turnstile widget), an HTTP 403, or a second HTTP 429 after one
backoff of 60 seconds (the crawl pauses for it) is recorded (source, URL, time, reason) in the gap report, the
source's spider is closed with nothing more requested, and the crawl moves on to the next source. It is never worked
around and never retried beyond that one backoff. A URL that the host's robots.txt disallows is never requested and
is recorded the same way. A server error (5xx) or a network error is retried once (a CDX lookup of the Internet
Archive three times); nothing else is retried.

The Internet Archive replays a page with the status the wiki gave when it was captured, so on `web.archive.org/web/...`
(the `REPLAY_HOSTS` setting) a 403 or a challenge page is an unusable capture, not a refusal: the next capture is
tried, and a quest with no usable capture left is `missing_snapshot` in the index. Only the archive's own 429 counts
there, backed off up to five times before it blocks `wiki_archive`. Its CDX server keeps the rule above.

Requests to a host go one at a time, at least 3 seconds apart, robots.txt included, under a plain user agent that
names the spider; Scrapy's AutoThrottle is off. The rule is the `StopRule` downloader middleware
(`spiralspider/middlewares.py`); the politeness settings are in `spiralspider/settings.py`.

## Sources

In priority order (`spiralspider sources` lists them):

| source | what it reads | gives |
| --- | --- | --- |
| `wiki_live` | `wiki.wizard101central.com`: `Category:<World>_Quests`, its subcategories and next pages, then each `Quest:<Name>` page | every field the wiki page has |
| `wiki_archive` | the Internet Archive's captures of the world's category pages (the newest raw capture with status 200 that lists members, found through the CDX), a CDX lookup per quest page for its newest captures, then each quest's snapshot (`/web/<ts>id_/`, else the playback form); only for quests `wiki_live` did not parse | the same fields |
| `spiraltracker` | `spiraltracker.com/<world>` | quest order, next quest, goal types |
| `folio` | `wizard101folio.com/<world>-quest-tree` | quest order, next quest, goal types |
| `forum_guide` | archived Wizard101 Central forum guides listed per world in `GUIDES` of `spiralspider/sources/forum_guide.py` (Celestia so far) | rewards |

The wiki pages are read with the parser of spiraltools (`spiraldb/tools/spiraltools/quests/archive.py`), imported from
the sibling checkout `../spiraldb/tools`, or from the directory `SPIRALTOOLS` names. The spiraltracker and folio
readers follow those sites' markup as of 2026-10-27 (spiraltracker's quest rows and step badges, folio's quest
tables), with the Dragonspyre pages of that day as their test fixtures; the forum guide reader assumes a markup (bold
quest names followed by "<n> XP" and "<n> Gold") that has not been checked against an archived guide.

Each source is a spider in `spiralspider/sources/`, named after the source. Only `wiki_live` goes through the browser
(scrapy-playwright); the others use Scrapy's plain downloader and its HTTP cache. robots.txt is always fetched by the
plain downloader.

Each quest's records are merged field by field: a field takes the value of the highest-priority source that has one,
and the spec's `source` names, per field, the source, URL and fetch time it came from.

## Run it in Docker

The image builds from this checkout and from `../spiraldb/tools` (a second build context, not a mount). The container
mounts only `./out` and `./cache`. Compose runs it as uid:gid 1000:1000 (set `SPIDER_UID` and `SPIDER_GID` if
`id -u` and `id -g` say otherwise) with `HOME=/tmp`, so it can write both. Create them first so they belong to you,
not to root:

```sh
mkdir -p out cache
docker compose build
docker compose run --rm spider crawl Celestia                    # every source
docker compose run --rm spider crawl Celestia --source live      # the live wiki only (or: archive)
docker compose run --rm spider gaps Celestia                     # print the last crawl's gap report
docker compose run --rm spider sources
```

The image is Microsoft's Playwright image (Chromium included) with Scrapy and scrapy-playwright installed. Without
compose:
`docker build --build-context spiraltools=../spiraldb/tools -t spiralspider .`

The world is one of the spiraltools world registry (`spiraldb/tools/spiraltools/worlds.py`); another name is refused
with the list of known worlds.

## Using your own browser

Set `SPIDER_CDP_URL` to the DevTools endpoint of a browser you run yourself (for example a browser container started
with `--remote-debugging-port=9222 --remote-debugging-address=0.0.0.0`, reachable from the spider container) and the
spider attaches to it over the Chrome DevTools Protocol (scrapy-playwright's `PLAYWRIGHT_CDP_URL`) instead of
launching its bundled Chromium:

```
SPIDER_CDP_URL=http://host.docker.internal:9222 docker compose run --rm spider crawl Celestia
```

Profile, cookies and extensions stay in your browser; the spider opens its pages in a new context of it and only
drives those. Two ready-made ways to reach it:

- a browser on this host: start it with remote debugging and use `http://host.docker.internal:9222` (the compose file
  maps that name to the host). A browser with a window listens on 127.0.0.1 only, which the container cannot reach;
  forward it to the Docker bridge first, e.g. `socat TCP-LISTEN:9222,fork,bind=172.17.0.1 TCP:127.0.0.1:9222`;
- a browser container: `docker-compose.browser.yml` adds a `browser` service on the spider's network (Microsoft's
  Playwright image with Chromium, DevTools on 9222) and points the spider at it:

```
docker compose -f docker-compose.yml -f docker-compose.browser.yml run --rm spider crawl Celestia
```

Swap the `browser` service's image for whatever browser you run; it only has to serve the DevTools endpoint on 9222.
The spider resolves the endpoint's host name to its address before connecting, because Chrome's DevTools server
answers only a Host header that is an address or localhost. The challenge rule is unchanged:
a challenge page, 403 or 429 storm is recorded and the crawl moves to the next source.

## Output

`out/<world>/` (`--out` moves it):

- `<id>.json`: a spec with no blocking gap, in the schema of `spiraldb/tools/README.md` ("Spec").
- `blocked/<id>.json`: a spec with a blocking gap. The sources give names, prerequisites and rewards; the client's
  keys a spec also needs (the `WizQst` lang, personas, mob and item adjectives) are not readable here, so every spec
  lists `lang`, `giver` and `goals` in `needs_review` as blocking, with the wiki's values, and lands here.
- `gap-report.json`: see below.

The ids are spiraltools' fallback ids, `<folder>-Q-<normalised title>` (`CL-Q-deeperanddeeper`); `requires` and
`successors` name the ids of the other quests of the crawl.

Copy `out/<world>/` into `spiraldb/tools/quest-specs/<world>/`; the `blocked/` folder is where the questgen glob does
not reach. A spec leaves `blocked/` only through the client-resolved pass: spiraltools reads the spider's wiki cache,
which uses its layout, resolves the client keys and writes the specs it can complete to `quest-specs/<world>/`:

```sh
python3 -I tools/spiraltools.py archive parse Celestia --cache ../spiralspider/cache/wiki_live
python3 -I tools/spiraltools.py archive parse Celestia --cache ../spiralspider/cache/wiki_archive
```

## Cache and provenance

`cache/<source>/` (`--cache` moves it) holds every page fetched, as `<timestamp>_<page>.html`, the timestamp being
the UTC fetch time (`wiki_archive`: the capture's timestamp). `wiki_live` and `wiki_archive` also write
`index-<world>.json` (quest name, page, zones, type), as spiraltools' archive cache does. A page already in the cache
is not fetched again; delete it to fetch it anew. The provenance of each spec field is in the spec's `source`.

`cache/httpcache/<source>/` is Scrapy's HTTP cache of the sources on the plain downloader (everything but
`wiki_live`): every response they got, robots.txt and the CDX index included, except refusals and server errors.
A response in it is not fetched again either; delete the folder to fetch everything anew.

## Gap report

`out/<world>/gap-report.json`, printed at the end of a crawl and by `spiralspider gaps <World>`:

- `sources`: per source, the quests it enumerated and parsed;
- `found`, `parsed`, `specs_ready`: quests listed by any source, quests with a record from any source, specs without
  a blocking gap;
- `blocked_sources`: each refusal under the stop rule (source, URL, reason, time);
- `errors`: a listing page (category lookup, quest listing, guide) a source got another HTTP error for, the source
  going on without it; and a record a source gave without a quest name, which gets no spec;
- `needs_review`: per spec field, how many specs have it blocking or to review;
- `missing_from_every_source`: quests some source listed that no source gave a record for.

## Tests

```sh
python3 -I -m unittest discover tests
```

No network and no browser: the challenge detector on saved challenge pages; the stop rule and the page cache as
middlewares on Scrapy responses; the politeness settings of every source and the `SPIDER_CDP_URL` mapping; the merge
priority; the spec writer against the schema; and each source spider's callbacks on a fixture. They need Scrapy and
scrapy-playwright installed (`pip install .`), and the spiraldb checkout beside this one (or `SPIRALTOOLS`).
