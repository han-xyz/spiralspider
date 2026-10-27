"""One quest's records from several sources, combined field by field in source priority, provenance kept per field."""
PRIORITY = ("wiki_live", "wiki_archive", "spiraltracker", "folio", "forum_guide")
EMPTY = (None, "", [], {})


def merge(records):
    """records: (fields, provenance) pairs for one quest. Each field takes the first non-empty value in PRIORITY order.

    Returns {"fields": {...}, "provenance": {field: provenance of the record it came from}}.
    """
    fields, provenance = {}, {}
    for record, source in sorted(records, key=lambda pair: PRIORITY.index(pair[1]["source"])):
        for field, value in record.items():
            if field not in fields and value not in EMPTY:
                fields[field], provenance[field] = value, source
    return {"fields": fields, "provenance": provenance}
