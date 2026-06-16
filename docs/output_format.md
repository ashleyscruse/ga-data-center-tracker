# Output Format

The deliverable for the Drawdown Georgia Solutions Tracker is an Excel (`.xlsx`) workbook in the structure Georgia Tech requires. Every dataset handed off conforms to this spec. The pipeline writes this format directly so delivery is mechanical, not manual.

## Workbook structure

Each workbook contains these sheets:

| Sheet | Required | Contents |
|---|---|---|
| `Original` | Yes | The original, unmodified source data as pulled. |
| `Transformed` | Only if transformations applied | Data after cleaning / transformation. |
| `Long` | Yes | Long format, exactly three columns: `county`, `varname`, `datavalue`. |
| `Data Description` | Yes | Source, vintage, date pulled, variable descriptions, original variable names, transformations applied. |
| `Codebook` | Yes | One row per variable: name, definition, units. |

## County name convention (strict)

Every county value in every sheet uses this exact form:

```
X County, Georgia
```

Example: `Fulton County, Georgia`. This is the join key the Solutions Tracker matches on, so the format is non-negotiable. The county reference table (`data/reference/`) is the single source of truth for these strings; nothing hand-types county names.

## Long sheet

The `Long` sheet is the integration target. Three columns only:

| Column | Meaning |
|---|---|
| `county` | County in `X County, Georgia` form. |
| `varname` | Variable name (matches a Codebook row). |
| `datavalue` | The value for that county and variable. |

One row per (county, variable). Counties with no value for a variable are represented explicitly per the methodology (zero vs. missing is defined there).

## Data Description sheet

Documents, per the GT requirement:
- Source
- Vintage (time period the data covers)
- Date pulled
- Description of each variable
- Original variable names (as they appeared in the source)
- Any transformations applied

## Notes

- The authoritative requirements memo from Georgia Tech lives in the gitignored `_planning/post-award/`; this file is the public, committed restatement of the format so the pipeline and methodology can reference it.
- Current GT integration leads: Derek and Snehal.
