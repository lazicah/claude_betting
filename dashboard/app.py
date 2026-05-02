"""
Betting Dashboard
=================
Dash-based live dashboard that reads scraped CSV files from match_database/
and displays:

  Tab 1 – Live Matches   : Latest snapshot per match per bookmaker, filterable.
  Tab 2 – Odds Comparison: Same match shown side-by-side across bookmakers.
  Tab 3 – Arbitrage      : Cross-bookmaker arbitrage opportunities.

Run locally:
    pip install dash plotly pandas rapidfuzz
    python dashboard/app.py

Via Docker Compose:
    docker compose up dashboard

Access:
    http://localhost:8050
"""

import glob as glob_module
import os
import re
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback, dcc, html, dash_table, no_update
from dash.exceptions import PreventUpdate
from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MATCH_DB = os.environ.get("MATCH_DB", "match_database")
REFRESH_INTERVAL_MS = 5_000  # 5 seconds

# All known bookmaker tags (scraperTag → display name)
BOOKMAKER_TAGS: dict[str, str] = {
    "1xb": "1xBet",
    "mlb": "Melbet",
    "22b": "22Bet",
    "bwn": "Betwinner",
    "888": "888Starz",
    "b9j": "Bet9ja",
    "spy": "Sportybet",
    "bta": "Betano",
    "bkg": "Betking",
    "afp": "Afropari",
    "pin": "Pinnacle",
    "lv": "LVBet",
    "sts": "STS",
    "bf": "Betfair",
    "bfx": "Betfair Exchange",
    "b365": "Bet365",
    "coin": "CoinCasino",
    "sbo": "Sbobet",
}

# Match status colour coding
STATUS_COLORS: dict[str, str] = {
    "HT": "#f0c040",   # yellow — half time
    "FT": "#808080",   # grey — full time
    "PEN": "#ff8c00",  # orange — penalties
    "AET": "#ff8c00",  # orange — after extra time
    "": "#4caf50",     # green — live/in-play
}

CSV_COLUMNS = [
    "timestamp", "match_time", "match_status",
    "home_score", "away_score",
    "odd_1", "odd_X", "odd_2",
    "total_line", "odd_over", "odd_under",
]

# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _tag_to_bookmaker(tag: str) -> str:
    return BOOKMAKER_TAGS.get(tag, tag)


def _parse_filename(filename: str) -> dict:
    """Extract team1, team2_league, tag, date from a CSV filename.

    Format: {team1}_vs_{team2}_{league}_{tag}_{date}.csv
    """
    name = filename[:-4] if filename.endswith(".csv") else filename

    # Date is always the final YYYY-MM-DD token
    date_match = re.search(r"_(\d{4}-\d{2}-\d{2})$", name)
    date_str = date_match.group(1) if date_match else ""
    if date_str:
        name = name[: -(len(date_str) + 1)]  # strip _YYYY-MM-DD

    # Split on _vs_ to get team1 and rest
    vs_idx = name.find("_vs_")
    if vs_idx == -1:
        return {"team1": name, "team2": "", "league": "", "tag": "", "date": date_str}

    team1 = name[:vs_idx].replace("_", " ").strip()
    after_vs = name[vs_idx + 4:]  # everything after "_vs_"

    # The tag is the last underscore-delimited token of after_vs.
    # Most tags have no underscores; betfair_ex is the exception, but
    # the folder name already identifies the bookmaker so we just
    # take the last segment as tag and everything else as team2/league.
    last_under = after_vs.rfind("_")
    if last_under == -1:
        tag = after_vs
        team2_league = ""
    else:
        tag = after_vs[last_under + 1:]
        team2_league = after_vs[:last_under].replace("_", " ").strip()

    # team2_league looks like "Chelsea Premier League"
    # We can't split team2 from league without extra knowledge, so use as-is.
    return {
        "team1": team1,
        "team2_league": team2_league,
        "tag": tag,
        "date": date_str,
    }


def _canonical(s: str) -> str:
    """Lower-case, strip punctuation/spaces — used for fuzzy grouping."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def load_latest_snapshots() -> pd.DataFrame:
    """Read the latest row from every CSV in match_database/ and return a DataFrame."""
    pattern = os.path.join(MATCH_DB, "*", "*", "*.csv")
    paths = sorted(glob_module.glob(pattern))

    records = []
    for path in paths:
        # Normalise separators, then split
        parts = path.replace("\\", "/").split("/")
        if len(parts) < 4:
            continue
        bookmaker_folder = parts[-3]
        filename = parts[-1]

        parsed = _parse_filename(filename)

        try:
            df = pd.read_csv(path, dtype=str)
        except Exception:
            continue
        df = df.dropna(how="all")
        if df.empty:
            continue

        last = df.iloc[-1].to_dict()

        # Derive a clean match label
        team1 = parsed["team1"]
        team2_league = parsed.get("team2_league", "")
        match_label = f"{team1} vs {team2_league}" if team2_league else team1

        last["bookmaker"] = bookmaker_folder
        last["bookmaker_display"] = _tag_to_bookmaker(parsed["tag"]) or bookmaker_folder
        last["match"] = match_label
        last["team1"] = team1
        last["team2_league"] = team2_league
        last["tag"] = parsed["tag"]
        last["date"] = parsed["date"]
        last["file_path"] = path
        records.append(last)

    if not records:
        return pd.DataFrame(
            columns=CSV_COLUMNS + ["bookmaker", "bookmaker_display", "match", "team1", "team2_league", "tag", "date"]
        )

    df_all = pd.DataFrame(records)

    # Coerce numeric columns
    for col in ["odd_1", "odd_X", "odd_2", "total_line", "odd_over", "odd_under"]:
        if col in df_all.columns:
            df_all[col] = pd.to_numeric(df_all[col], errors="coerce")

    return df_all


# ---------------------------------------------------------------------------
# Arbitrage helpers
# ---------------------------------------------------------------------------

def _arb_margin(odd1: float, oddX: float, odd2: float) -> Optional[float]:
    """Return the arbitrage margin (1 - sum_of_implied_probs).

    Positive value = profit opportunity.
    Returns None if any odd is missing/invalid.
    """
    try:
        impl = 1.0 / odd1 + 1.0 / oddX + 1.0 / odd2
        return round((1.0 - impl) * 100, 2)  # as percentage
    except (TypeError, ZeroDivisionError):
        return None


def _best_odds_across_bookmakers(group_df: pd.DataFrame) -> dict:
    """Return the best (highest) odd for each market across a group of rows."""
    best: dict[str, tuple] = {}  # market → (value, bookmaker)
    for _, row in group_df.iterrows():
        for market in ["odd_1", "odd_X", "odd_2"]:
            val = row.get(market)
            if pd.notna(val) and (market not in best or val > best[market][0]):
                best[market] = (val, row.get("bookmaker_display", ""))
    return best


def find_arbitrage(df: pd.DataFrame) -> pd.DataFrame:
    """Group same match across bookmakers and calculate arbitrage margin."""
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["_key"] = df["team1"].apply(_canonical) + "__" + df["team2_league"].apply(_canonical)

    groups: dict[str, list] = {}
    for _, row in df.iterrows():
        key = row["_key"]
        groups.setdefault(key, []).append(row)

    results = []
    for key, rows in groups.items():
        group_df = pd.DataFrame(rows)
        if group_df["bookmaker"].nunique() < 2:
            continue

        best = _best_odds_across_bookmakers(group_df)
        if len(best) < 3:
            continue

        o1, bm1 = best["odd_1"]
        oX, bmX = best["odd_X"]
        o2, bm2 = best["odd_2"]
        margin = _arb_margin(o1, oX, o2)
        if margin is None:
            continue

        sample = group_df.iloc[0]
        results.append(
            {
                "match": sample["match"],
                "bookmakers": ", ".join(sorted(group_df["bookmaker_display"].unique())),
                "best_odd_1": f"{o1:.2f} ({bm1})",
                "best_odd_X": f"{oX:.2f} ({bmX})",
                "best_odd_2": f"{o2:.2f} ({bm2})",
                "arb_margin_%": margin,
                "profitable": margin > 0,
            }
        )

    arb_df = pd.DataFrame(results)
    if not arb_df.empty:
        arb_df = arb_df.sort_values("arb_margin_%", ascending=False)
    return arb_df


# ---------------------------------------------------------------------------
# Odds comparison helpers
# ---------------------------------------------------------------------------

def build_comparison_table(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot latest odds across bookmakers per match."""
    if df.empty:
        return pd.DataFrame()

    cols = ["match", "bookmaker_display", "match_time", "match_status",
            "home_score", "away_score", "odd_1", "odd_X", "odd_2",
            "total_line", "odd_over", "odd_under"]
    df = df[[c for c in cols if c in df.columns]].copy()
    return df


# ---------------------------------------------------------------------------
# App layout
# ---------------------------------------------------------------------------

HEADER_STYLE = {
    "background": "#1a1a2e",
    "padding": "12px 24px",
    "display": "flex",
    "alignItems": "center",
    "justifyContent": "space-between",
    "borderBottom": "2px solid #e94560",
}

TITLE_STYLE = {
    "color": "#e94560",
    "fontSize": "22px",
    "fontWeight": "bold",
    "margin": "0",
}

BADGE_STYLE = {
    "background": "#0f3460",
    "color": "#e2e2e2",
    "borderRadius": "6px",
    "padding": "4px 12px",
    "fontSize": "13px",
}

CONTROLS_STYLE = {
    "background": "#16213e",
    "padding": "12px 24px",
    "display": "flex",
    "alignItems": "center",
    "gap": "16px",
    "flexWrap": "wrap",
    "borderBottom": "1px solid #0f3460",
}

DROPDOWN_STYLE = {"minWidth": "160px", "background": "#0f3460"}

TABLE_STYLE = {
    "backgroundColor": "#16213e",
    "color": "#e2e2e2",
    "border": "none",
}

TABLE_HEADER_STYLE = {
    "backgroundColor": "#0f3460",
    "color": "#e94560",
    "fontWeight": "bold",
    "textAlign": "center",
}

TABLE_CELL_STYLE = {
    "backgroundColor": "#16213e",
    "color": "#e2e2e2",
    "border": "1px solid #0f3460",
    "textAlign": "center",
    "padding": "8px",
    "fontSize": "13px",
}

app = Dash(
    __name__,
    title="Betting Dashboard",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

app.layout = html.Div(
    style={"fontFamily": "Inter, Arial, sans-serif", "background": "#0d0d1a", "minHeight": "100vh"},
    children=[
        # Header
        html.Div(
            style=HEADER_STYLE,
            children=[
                html.H1("⚽ Betting Dashboard", style=TITLE_STYLE),
                html.Div(
                    id="refresh-badge",
                    children="⟳ Auto-refresh: 5s",
                    style=BADGE_STYLE,
                ),
            ],
        ),

        # Controls bar
        html.Div(
            style=CONTROLS_STYLE,
            children=[
                html.Label("Bookmaker:", style={"color": "#aaa", "fontSize": "13px"}),
                dcc.Dropdown(
                    id="filter-bookmaker",
                    options=[{"label": "All", "value": "ALL"}],
                    value="ALL",
                    clearable=False,
                    style=DROPDOWN_STYLE,
                ),
                html.Label("Status:", style={"color": "#aaa", "fontSize": "13px"}),
                dcc.Dropdown(
                    id="filter-status",
                    options=[
                        {"label": "All", "value": "ALL"},
                        {"label": "Live", "value": "LIVE"},
                        {"label": "Half-time", "value": "HT"},
                        {"label": "Full-time", "value": "FT"},
                    ],
                    value="ALL",
                    clearable=False,
                    style=DROPDOWN_STYLE,
                ),
                html.Label("Min arb margin (%):", style={"color": "#aaa", "fontSize": "13px"}),
                dcc.Input(
                    id="filter-arb-margin",
                    type="number",
                    value=0,
                    min=-100,
                    max=100,
                    step=0.1,
                    style={
                        "width": "80px",
                        "background": "#0f3460",
                        "color": "#e2e2e2",
                        "border": "1px solid #e94560",
                        "borderRadius": "4px",
                        "padding": "4px 8px",
                    },
                ),
                html.Div(
                    id="stats-bar",
                    style={"marginLeft": "auto", "color": "#aaa", "fontSize": "13px"},
                ),
            ],
        ),

        # Tabs
        dcc.Tabs(
            id="tabs",
            value="live",
            style={"background": "#16213e"},
            colors={"border": "#0f3460", "primary": "#e94560", "background": "#16213e"},
            children=[
                dcc.Tab(label="Live Matches", value="live",
                        style={"color": "#aaa", "background": "#16213e"},
                        selected_style={"color": "#e94560", "background": "#1a1a2e", "fontWeight": "bold"}),
                dcc.Tab(label="Odds Comparison", value="compare",
                        style={"color": "#aaa", "background": "#16213e"},
                        selected_style={"color": "#e94560", "background": "#1a1a2e", "fontWeight": "bold"}),
                dcc.Tab(label="Arbitrage Finder", value="arb",
                        style={"color": "#aaa", "background": "#16213e"},
                        selected_style={"color": "#e94560", "background": "#1a1a2e", "fontWeight": "bold"}),
            ],
        ),

        # Tab content
        html.Div(id="tab-content", style={"padding": "16px"}),

        # Hidden stores
        dcc.Store(id="data-store"),

        # Auto-refresh interval
        dcc.Interval(id="interval", interval=REFRESH_INTERVAL_MS, n_intervals=0),
    ],
)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@app.callback(
    Output("data-store", "data"),
    Output("filter-bookmaker", "options"),
    Output("stats-bar", "children"),
    Input("interval", "n_intervals"),
)
def refresh_data(n):
    """Load the latest CSV snapshots and cache them in the Store."""
    df = load_latest_snapshots()

    if df.empty:
        bookmaker_opts = [{"label": "All", "value": "ALL"}]
        stats = "No data found. Start the scrapers and check match_database/."
        return df.to_json(date_format="iso", orient="split"), bookmaker_opts, stats

    bookmakers = sorted(df["bookmaker_display"].dropna().unique())
    bookmaker_opts = [{"label": "All", "value": "ALL"}] + [
        {"label": b, "value": b} for b in bookmakers
    ]

    n_matches = df["match"].nunique()
    n_books = df["bookmaker"].nunique()
    stats = f"📊 {len(df)} feeds · {n_matches} matches · {n_books} bookmakers"

    return df.to_json(date_format="iso", orient="split"), bookmaker_opts, stats


@app.callback(
    Output("tab-content", "children"),
    Input("tabs", "value"),
    Input("data-store", "data"),
    Input("filter-bookmaker", "value"),
    Input("filter-status", "value"),
    Input("filter-arb-margin", "value"),
)
def render_tab(tab, data_json, bookmaker_filter, status_filter, min_arb):
    if not data_json:
        return html.P("Loading data…", style={"color": "#aaa"})

    df = pd.read_json(data_json, orient="split")

    if df.empty:
        return html.P(
            "No CSV files found in match_database/. Start the scrapers first.",
            style={"color": "#f0a040", "padding": "20px"},
        )

    # Apply bookmaker filter
    if bookmaker_filter and bookmaker_filter != "ALL":
        df = df[df["bookmaker_display"] == bookmaker_filter]

    # Apply status filter
    if status_filter and status_filter != "ALL":
        if status_filter == "LIVE":
            df = df[df["match_status"].fillna("").isin(["", None])]
        else:
            df = df[df["match_status"].fillna("") == status_filter]

    if tab == "live":
        return _render_live_tab(df)
    elif tab == "compare":
        return _render_compare_tab(df)
    elif tab == "arb":
        min_margin = float(min_arb) if min_arb is not None else 0.0
        return _render_arb_tab(df, min_margin)

    return html.P("Unknown tab", style={"color": "red"})


# ---------------------------------------------------------------------------
# Tab renderers
# ---------------------------------------------------------------------------

def _status_badge(status: str) -> str:
    """Return a labelled status string."""
    labels = {"HT": "⏸ HT", "FT": "✓ FT", "PEN": "🅿 PEN", "AET": "⟳ AET", "": "🔴 LIVE"}
    return labels.get(status, status or "🔴 LIVE")


def _render_live_tab(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.P("No matches found for the selected filters.", style={"color": "#aaa"})

    display_cols = [
        ("bookmaker_display", "Bookmaker"),
        ("match", "Match"),
        ("match_status", "Status"),
        ("match_time", "Time"),
        ("home_score", "Home"),
        ("away_score", "Away"),
        ("odd_1", "Odd 1"),
        ("odd_X", "Odd X"),
        ("odd_2", "Odd 2"),
        ("total_line", "Line"),
        ("odd_over", "Over"),
        ("odd_under", "Under"),
        ("timestamp", "Updated"),
    ]

    available = [(c, lbl) for c, lbl in display_cols if c in df.columns]
    table_df = df[[c for c, _ in available]].copy()
    table_df.columns = [lbl for _, lbl in available]

    # Format numeric columns
    for col in ["Odd 1", "Odd X", "Odd 2", "Over", "Under"]:
        if col in table_df.columns:
            table_df[col] = pd.to_numeric(table_df[col], errors="coerce").apply(
                lambda x: f"{x:.2f}" if pd.notna(x) else ""
            )

    # Format Status as badge
    if "Status" in table_df.columns:
        table_df["Status"] = table_df["Status"].fillna("").apply(_status_badge)

    # Sort: live first, then by match name
    if "Status" in table_df.columns:
        table_df["_sort"] = table_df["Status"].apply(lambda s: 0 if "LIVE" in s else 1)
        table_df = table_df.sort_values(["_sort", "Match"]).drop(columns=["_sort"])

    return html.Div(
        [
            html.P(
                f"{len(table_df)} match feeds",
                style={"color": "#aaa", "fontSize": "13px", "marginBottom": "8px"},
            ),
            dash_table.DataTable(
                data=table_df.to_dict("records"),
                columns=[{"name": c, "id": c} for c in table_df.columns],
                style_table={"overflowX": "auto"},
                style_header=TABLE_HEADER_STYLE,
                style_cell=TABLE_CELL_STYLE,
                style_data_conditional=_live_status_styles(),
                page_size=50,
                sort_action="native",
                filter_action="native",
                filter_options={"case": "insensitive"},
            ),
        ]
    )


def _live_status_styles() -> list:
    """Conditional formatting rules for live/HT/FT status badges."""
    return [
        {
            "if": {"filter_query": '{Status} contains "LIVE"', "column_id": "Status"},
            "color": "#4caf50",
            "fontWeight": "bold",
        },
        {
            "if": {"filter_query": '{Status} contains "HT"', "column_id": "Status"},
            "color": "#f0c040",
            "fontWeight": "bold",
        },
        {
            "if": {"filter_query": '{Status} contains "FT"', "column_id": "Status"},
            "color": "#808080",
        },
        {
            "if": {"filter_query": '{Status} contains "PEN" || {Status} contains "AET"', "column_id": "Status"},
            "color": "#ff8c00",
            "fontWeight": "bold",
        },
        {"if": {"row_index": "odd"}, "backgroundColor": "#1a1a2e"},
    ]


def _render_compare_tab(df: pd.DataFrame) -> html.Div:
    """Show each unique match with all bookmakers' odds in one row per bookmaker."""
    if df.empty:
        return html.P("No matches found for the selected filters.", style={"color": "#aaa"})

    compare_df = build_comparison_table(df)

    display_cols = [
        ("match", "Match"),
        ("bookmaker_display", "Bookmaker"),
        ("match_status", "Status"),
        ("home_score", "Home"),
        ("away_score", "Away"),
        ("odd_1", "Odd 1"),
        ("odd_X", "Odd X"),
        ("odd_2", "Odd 2"),
        ("total_line", "Line"),
        ("odd_over", "Over"),
        ("odd_under", "Under"),
    ]
    available = [(c, lbl) for c, lbl in display_cols if c in compare_df.columns]
    table_df = compare_df[[c for c, _ in available]].copy()
    table_df.columns = [lbl for _, lbl in available]

    for col in ["Odd 1", "Odd X", "Odd 2", "Over", "Under"]:
        if col in table_df.columns:
            table_df[col] = pd.to_numeric(table_df[col], errors="coerce").apply(
                lambda x: f"{x:.2f}" if pd.notna(x) else ""
            )

    if "Status" in table_df.columns:
        table_df["Status"] = table_df["Status"].fillna("").apply(_status_badge)

    table_df = table_df.sort_values(["Match", "Bookmaker"]) if "Match" in table_df.columns else table_df

    return html.Div(
        [
            html.P(
                "Compare odds for the same match across all bookmakers. Use the filter bar above to narrow by bookmaker.",
                style={"color": "#aaa", "fontSize": "13px", "marginBottom": "8px"},
            ),
            dash_table.DataTable(
                data=table_df.to_dict("records"),
                columns=[{"name": c, "id": c} for c in table_df.columns],
                style_table={"overflowX": "auto"},
                style_header=TABLE_HEADER_STYLE,
                style_cell=TABLE_CELL_STYLE,
                style_data_conditional=_live_status_styles() + [
                    {"if": {"row_index": "odd"}, "backgroundColor": "#1a1a2e"},
                ],
                page_size=100,
                sort_action="native",
                filter_action="native",
                filter_options={"case": "insensitive"},
            ),
        ]
    )


def _render_arb_tab(df: pd.DataFrame, min_margin: float) -> html.Div:
    """Find and display cross-bookmaker arbitrage opportunities."""
    arb_df = find_arbitrage(df)

    if arb_df.empty:
        msg = (
            "No multi-bookmaker matches found yet. "
            "Arbitrage detection requires the same match to be live on at least 2 bookmakers simultaneously."
        )
        return html.P(msg, style={"color": "#aaa", "padding": "20px"})

    # Apply margin filter
    arb_df = arb_df[arb_df["arb_margin_%"] >= min_margin].copy()

    if arb_df.empty:
        return html.P(
            f"No arbitrage opportunities with margin ≥ {min_margin}%.",
            style={"color": "#aaa", "padding": "20px"},
        )

    n_profitable = (arb_df["arb_margin_%"] > 0).sum()

    table_df = arb_df.drop(columns=["profitable"]).copy()
    table_df["arb_margin_%"] = table_df["arb_margin_%"].apply(lambda x: f"{x:+.2f}%")

    conditional_styles = [
        {
            "if": {
                "filter_query": "{arb_margin_%} contains '+'",
                "column_id": "arb_margin_%",
            },
            "color": "#4caf50",
            "fontWeight": "bold",
            "backgroundColor": "#0d2e1a",
        },
        {
            "if": {
                "filter_query": "{arb_margin_%} contains '-'",
                "column_id": "arb_margin_%",
            },
            "color": "#e94560",
        },
        {"if": {"row_index": "odd"}, "backgroundColor": "#1a1a2e"},
    ]

    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        f"💰 {n_profitable} profitable arbitrage",
                        style={"color": "#4caf50", "fontWeight": "bold", "marginRight": "16px"},
                    ),
                    html.Span(
                        f"| {len(arb_df)} total opportunities shown (margin ≥ {min_margin}%)",
                        style={"color": "#aaa"},
                    ),
                ],
                style={"marginBottom": "10px", "fontSize": "13px"},
            ),
            html.P(
                "A positive margin means guaranteed profit by betting proportionally on all outcomes across bookmakers.",
                style={"color": "#777", "fontSize": "12px", "marginBottom": "12px"},
            ),
            dash_table.DataTable(
                data=table_df.to_dict("records"),
                columns=[{"name": c, "id": c} for c in table_df.columns],
                style_table={"overflowX": "auto"},
                style_header=TABLE_HEADER_STYLE,
                style_cell=TABLE_CELL_STYLE,
                style_data_conditional=conditional_styles,
                page_size=50,
                sort_action="native",
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Betting Dashboard (Dash)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8050, help="Port (default: 8050)")
    parser.add_argument("--debug", action="store_true", help="Enable Dash debug mode")
    parser.add_argument(
        "--db",
        default=None,
        help="Path to match_database/ directory (overrides MATCH_DB env var)",
    )
    args = parser.parse_args()

    if args.db:
        MATCH_DB = args.db

    app.run(host=args.host, port=args.port, debug=args.debug)
