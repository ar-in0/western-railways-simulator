import timetable as tt
import dash
import pandas as pd
from dash import Dash, html, dcc, Input, Output, State, callback_context
import dash_bootstrap_components as dbc
import io
import base64
import plotly.graph_objs as go
import copy
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from timetable import Direction
import time
import utils
from dash import dash_table
from dash.exceptions import PreventUpdate
from timetable import Line


from enum import Enum

class FilterType(Enum):
    RAKELINK = 'rakelink'
    SERVICE = 'service'
    STATION = 'station'


@dataclass
class FilterQuery:
    type: Optional[FilterType] = None
    
    # Make fields mode-specific (no properties needed)
    startStation: Optional[str] = None
    endStation: Optional[str] = None
    passingThrough: List[str] = field(default_factory=list)
    inTimePeriod: Optional[Tuple[int, int]] = (165, 1605)
    
    ac: Optional[bool] = None
    inDirection: Optional[List[str]] = None
    selectedLinks: List[str] = field(default_factory=list)
    selectedServices: List[str] = field(default_factory=list)

def visualization_layout(graph_ready):
    return dcc.Graph(
        id="rake-3d-graph",
        style={
            "height": "75vh",
            "display": "block" if graph_ready else "none"
        }
    )

def service_details_layout():
    return html.Div("...", style={"padding": "20px"})

def fmt_time(t):
    if t is None:
        return "--:--"

    t = int(round(t))   # or int(t) if you prefer floor
    return f"{t//60:02d}:{t%60:02d}"


class Simulator:
    def __init__(self):
        self.app = Dash(external_stylesheets=[dbc.themes.BOOTSTRAP])
        self.parser = None
        self.wttContents = None
        self.summaryContents = None
        self.wttFileName = None
        self.summaryFileName = None

        # set initial layout
        self.app.layout = self.drawLayout()
        self.initCallbacks()
        self.linkTimingsCreated = False

        self.query = FilterQuery()
        self.query.type = FilterType.RAKELINK

        self.filterStates = {
            FilterType.RAKELINK: {},
            FilterType.SERVICE: {},
            FilterType.STATION: {}
        }

    def build_query_info_panel(self):
        if self.query.type == FilterType.RAKELINK:
            return self.build_rake_link_query_info()
        elif self.query.type == FilterType.SERVICE:
            return self.build_service_query_info()
        else:
            return html.Div("No query context available.")
    
    def build_service_query_info(self):
        if not self.query.selectedServices:
            return html.Div("No services selected.")
        
        # Find selected service objects
        selected_svcs = [
            svc for svc in self.parser.wtt.suburbanServices
            if any(str(sid) in self.query.selectedServices for sid in svc.serviceId)
        ]
        
        return html.Div(
            [
                html.Div(
                    "Selected Services",
                    style={
                        "fontSize": "13px",
                        "fontWeight": "600",
                        "color": "#475569",
                        "marginBottom": "6px"
                    }
                ),
                *[self.build_service_detail_block(svc) for svc in selected_svcs]
            ],
            style={"padding": "8px"}
        )

    def build_service_detail_block(self, svc):
        svc_id_str = ','.join(str(sid) for sid in svc.serviceId)
        
        return html.Div(
            [
                html.Div(
                    f"Service {svc_id_str}",
                    style={"fontWeight": "600", "marginBottom": "4px"}
                ),
                html.Div(
                    f"{svc.direction.name} | {svc.initStation.name} → {svc.finalStation.name}",
                    style={"fontSize": "12px", "color": "#64748b"}
                ),
                html.Div(
                    f"{'AC' if svc.needsACRake else 'Non-AC'} | {svc.rakeSizeReq}-car | {len(svc.events)} stops",
                    style={"fontSize": "12px", "color": "#64748b", "marginBottom": "8px"}
                ),
                html.Hr(style={"margin": "8px 0"})
            ]
        )

    def build_rake_link_query_info(self):
        if not self.query.selectedLinks:
            return html.Div("No rake links selected.")

        selected_rcs = [
            rc for rc in self.parser.wtt.rakecycles
            if rc.linkName in self.query.selectedLinks
        ]

        return html.Div(
            [
                html.Div(
                    "Selected Rake Links",
                    style={
                        "fontSize": "13px",
                        "fontWeight": "600",
                        "color": "#475569",
                        "marginBottom": "6px"
                    }
                ),
                *[self.build_rake_path_block(rc) for rc in selected_rcs]
            ],
            style={"padding": "8px"}
        )

    def build_rake_path_block(self, rc):
        services = rc.servicePath
        n = len(services)

        start = services[0].initStation.name
        end = services[-1].finalStation.name

        ac = sum(1 for s in services if s.needsACRake)

        return html.Details(
            [
                html.Summary(
                    [
                        html.Span(
                            f"Rake {rc.linkName}",
                            style={"fontWeight": "600"}
                        ),
                        html.Span(
                            f"  · {len(services)} services ·  ",
                            style={"color": "#64748b"}
                        ),
                        html.Span(
                            f"{start} → {end}"
                        ),
                        html.Span(
                            f"  {'AC' if ac == len(services) else 'Non-AC' if ac == 0 else 'Mixed AC'}",
                            style={"marginLeft": "6px", "color": "#475569"}
                        ),
                    ],
                    style={
                        "cursor": "pointer",
                        "fontSize": "13px",
                        "lineHeight": "1.4"
                    }
                ),

                html.Div(
                    [self.build_service_row(svc, i < n - 1)
                    for i, svc in enumerate(services)],
                    style={"marginLeft": "14px", "marginTop": "6px"}
                )
            ]
        )



    def build_minimal_rake_block(self, rc):
        rows = []
        for i, svc in enumerate(rc.servicePath, start=1):
            rows.append({
                "seq": i,
                "service_id": ", ".join(str(s) for s in svc.serviceId),
                "start": svc.initStation.name,
                "end": svc.finalStation.name,
                "ac": "AC" if svc.needsACRake else "Non-AC",
            })

        return html.Div(
            [
                html.Div(
                    f"Rake {rc.linkName} | "
                    f"{'AC' if rc.rake.isAC else 'Non-AC'} | "
                    f"{rc.rake.rakeSize} cars | "
                    f"{rc.lengthKm:.1f} km | "
                    f"{len(rc.servicePath)} services",
                    style={"fontWeight": "600", "marginBottom": "4px"}
                ),

                dash_table.DataTable(
                    columns=[
                        {"name": "#", "id": "seq"},
                        {"name": "Service ID", "id": "service_id"},
                        {"name": "From", "id": "start"},
                        {"name": "To", "id": "end"},
                        {"name": "AC?", "id": "ac"},
                    ],
                    data=rows,
                    page_size=8,
                    style_table={"maxHeight": "200px", "overflowY": "auto"},
                    style_cell={"fontSize": "12px", "padding": "4px"},
                ),

                html.Hr()
            ]
        )

    def build_service_row(self, svc, draw_connector):
        row = html.Div(
            [
                html.Span(
                    str(svc.serviceId),
                    style={"minWidth": "56px", "display": "inline-block"}
                ),
                html.Span(
                    f"{svc.initStation.name} → {svc.finalStation.name} ({svc.direction})",
                    style={"marginLeft": "6px"}
                ),
                html.Span(
                    fmt_time(
                        next((e.atTime for e in svc.events if e.atTime is not None), None)
                    ),
                    style={"marginLeft": "6px", "color": "#64748b"}
                ),
            ],
            style={"fontSize": "12px"}
        )

        if not draw_connector:
            return row

        return html.Div([row, html.Div("│", style={"marginLeft": "6px"})])


    def _reset_render_flags(self):
        for rc in self.parser.wtt.rakecycles:
            rc.render = True

        for svc in self.parser.wtt.suburbanServices:
            if not svc.events:
                svc.render = False
                continue
            svc.render = True
            for ev in svc.events:
                ev.render = True

    def _apply_filters(self, qq):
        if qq.type == FilterType.SERVICE:
            self.applyServiceFilters(qq)
        elif qq.type == FilterType.STATION:
            self.applyStationFilters(qq)
        else:
            self.applyLinkFilters(qq)

    def _post_process_station_mode(self, fig, qq):
        if qq.type != FilterType.STATION:
            return fig

        fig.update_layout(
            scene_camera=dict(eye=dict(x=0, y=0, z=1.5)),
            scene=dict(aspectratio=dict(x=3, y=1.5, z=1.2))
        )

        for i, rc in enumerate(self.parser.wtt.rakecycles):
            for svc in rc.servicePath:
                if i < len(self.parser.wtt.rakecycles)/2 + 10:
                    svc.needsACRake = True

        before = utils.corridorMixingMinimal(qq.startStation, qq.endStation, qq.inTimePeriod[0], qq.inTimePeriod[1])
        after = utils.corridorMixingMinimal(qq.startStation, qq.endStation, qq.inTimePeriod[0], qq.inTimePeriod[1])

        print("=== Mixing Report ===")
        for b, a in zip(before, after):
            print(f"{b['station']}: {b['mixing_score']:.3f} -> {a['mixing_score']:.3f}")

        return fig
    
    def _reset_isolation(self, fig):
        for rc in self.parser.wtt.rakecycles:
            rc.render = True
        fig.update_layout(annotations=[])
        for tr in fig.data:
            tr.opacity = 1.0
            if hasattr(tr, "line"): tr.line.width = 2
            if hasattr(tr, "marker"): tr.marker.size = 2
        return fig

    def _highlight_clicked_services(self, fig, selected_services):
        """
        Highlight selected services in the visualization.
        
        Args:
            fig: Plotly figure object
            selected_services: List of service ID strings (e.g., ["93001", "93002"])
        """
        if not selected_services:
            return
        
        selected_set = set(selected_services)
        
        for trace in fig.data:
            # Trace names in service mode are "LinkName-ServiceID"
            # e.g., "A-93001"
            if '-' in trace.name:
                trace_service = trace.name.split('-')[1]  # Extract service ID
                
                if trace_service in selected_set:
                    # Highlight
                    trace.opacity = 1.0
                    if hasattr(trace, "marker"): 
                        trace.marker.size = 3
                else:
                    # Dim
                    trace.opacity = 0.35
                    if hasattr(trace, "marker"): 
                        trace.marker.size = 1
            else:
                # Not a service trace (maybe context traces), dim by default
                trace.opacity = 0.35
    
    def _highlight_clicked(self, fig, selected_links):
        """
        Highlight one or more rake links in the visualization.
        
        Args:
            fig: Plotly figure object
            selected_links: Either a string (single link) or list of strings (multiple links)
        """
        # Normalize to list for uniform handling
        if isinstance(selected_links, str):
            selected_links = [selected_links]
        
        if not selected_links:
            # # No selection - reset all to normal
            # for trace in fig.data:
            #     trace.opacity = 1.0
            #     if hasattr(trace, "line"): 
            #         trace.line.width = 2
            #     if hasattr(trace, "marker"): 
            #         trace.marker.size = 2
            return
        
        selected_set = set(selected_links)
        
        for trace in fig.data:
            # Extract base link name (handle "A" or "A-93001" format)
            trace_link = trace.name.split('-')[0] if '-' in trace.name else trace.name
            
            if trace_link in selected_set:
                # Highlight selected traces
                trace.opacity = 1.0
                # if hasattr(trace, "line"): 
                #     trace.line.width = 4  # Thicker than default
                if hasattr(trace, "marker"): 
                    trace.marker.size = 3  # Larger than default
            else:
                # Dim unselected traces
                trace.opacity = 0.35
                # if hasattr(trace, "line"): 
                #     trace.line.width = 2
                if hasattr(trace, "marker"): 
                    trace.marker.size = 1

    def _build_annotation(self, rc):
        return [
            dict(
                x=0.02, y=0.97,
                xref="paper", yref="paper",
                showarrow=False,
                align="left",
                bgcolor="rgba(0,0,0,0.75)",
                bordercolor="rgba(255,255,255,0.9)",
                borderwidth=2,
                borderpad=8,
                font=dict(size=14, color="white"),
                text=(
                    f"<b>Rake Link {rc.linkName}</b><br>"
                    f"Services: {len(rc.servicePath)}<br>"
                    f"Start: {rc.servicePath[0].initStation.name}<br>"
                    f"End: {rc.servicePath[-1].finalStation.name}<br>"
                    f"Distance: {int(rc.lengthKm)} km<br>"
                    f"Rake: {'AC' if rc.rake.isAC else 'Non-AC'} ({rc.rake.rakeSize}-car)<br>"
                )
            )
        ]
    
    def drawLayout(self):
            return html.Div(
                [
                    # Hidden store (optional)
                    dcc.Store(id="rl-table-store"),
                    dcc.Store(id="app-state"),

                    # === LEFT SIDEBAR ===
                    html.Div(
                        [
                            # Title + Subtitle
                            html.Div(
                                [
                                    dcc.Markdown(
                                        '''
                                        ### Western Railways – Timetable Visualizer
                                        '''.replace("  ", ""),
                                        className="title",
                                    ),
                                    dcc.Markdown(
                                        '''
                                        Interactive tool to analyze rake-links during migration to AC.
                                        '''.replace("  ", ""),
                                        className="subtitle",
                                    ),
                                ]
                            ),

                            html.Hr(),
                            html.Div([
                                dcc.Markdown("##### Upload Required Files", className="subtitle"),
                            ], style={"padding": "8px 0px"}),

                            # Upload components
                            dbc.Row([
                                # Upload Full WTT
                                dbc.Col([
                                    dcc.Upload(
                                        id="upload-wtt-inline",
                                        children=html.Div([
                                            html.Img(
                                                src="/assets/excel-icon.png",
                                                style={
                                                    "width": "28px",
                                                    "height": "28px",
                                                    "marginBottom": "6px"
                                                }
                                            ),
                                            html.Div("Full WTT", 
                                                    style={"fontWeight": "500", "color": "#334155", "fontSize": "14px"}),
                                            html.Div("Click to upload",
                                                    style={"fontSize": "11px", "color": "#94a3b8", "marginTop": "4px"})
                                        ], className="text-center"),
                                        style={
                                            "height": "140px",
                                            "borderWidth": "2px",
                                            "borderStyle": "dashed",
                                            "borderRadius": "12px",
                                            "borderColor": "#cbd5e1",
                                            "display": "flex",
                                            "alignItems": "center",
                                            "justifyContent": "center",
                                            "cursor": "pointer",
                                            "transition": "all 0.2s ease",
                                        },
                                        multiple=False
                                    )
                                ], xs=12, md=6, className="mb-3 mb-md-0"),

                                # Upload Rake-Link Summary
                                dbc.Col([
                                    dcc.Upload(
                                        id="upload-summary-inline",
                                        children=html.Div([
                                            html.Img(
                                                src="/assets/excel-icon.png",
                                                style={
                                                    "width": "28px",
                                                    "height": "28px",
                                                    "marginBottom": "6px"
                                                }
                                            ),
                                            html.Div("Rake-Link Summary", 
                                                    style={"fontWeight": "500", "color": "#334155", "fontSize": "14px"}),
                                            html.Div("Click to upload",
                                                    style={"fontSize": "11px", "color": "#94a3b8", "marginTop": "4px"})
                                        ], className="text-center"),
                                        style={
                                            "height": "140px",
                                            "borderWidth": "2px",
                                            "borderStyle": "dashed",
                                            "borderRadius": "12px",
                                            "borderColor": "#cbd5e1",
                                            "display": "flex",
                                            "alignItems": "center",
                                            "justifyContent": "center",
                                            "cursor": "pointer",
                                            "transition": "all 0.2s ease",
                                        },
                                        multiple=False
                                    )
                                ], xs=12, md=6)
                            ], style={"padding": "0px 35px", "marginBottom": "20px"}),

                            html.Hr(),  

                            # Filters
                            html.Div([
                                html.Div([
                                    dcc.Markdown("##### View", className="subtitle"),
                                ], style={"padding": "0px 0px"}),

                                # --- SHARED AC FILTER ---
                                # Moved AC selector here, outside the tabs
                                dbc.RadioItems(
                                    id="ac-selector", # ID remains the same
                                    options=[
                                        {"label": "All", "value": "all"},
                                        {"label": "AC", "value": "ac"},
                                        {"label": "Non-AC", "value": "nonac"},
                                    ],
                                    value="all",
                                    inline=True,
                                    inputStyle={"marginRight": "6px"},
                                    labelStyle={"marginRight": "12px", "fontSize": "13px"},
                                    style={"marginTop": "8px", "marginBottom": "8px", "padding": "0px 35px"}
                                ),

                                # --- TABBED FILTERS ---
                                html.Div(id="filter-overlay", style={"display": "none"}), 
                                dbc.Tabs(
                                    id="filter-tabs",
                                    active_tab="tab-rakelink", # Default to rake link
                                    children=[
                                        # --- TAB 1: RAKE LINK FILTERS (Original IDs) ---
                                        dbc.Tab(
                                            label="Rake Links",
                                            tab_id="tab-rakelink",
                                            children=dbc.Card(
                                                [
                                                    dbc.CardBody([
                                                        # Start & End Stations side by side
                                                        dbc.Row([
                                                            dbc.Col([
                                                                html.Label("Start Station", className="criteria-label"),
                                                                dcc.Dropdown(
                                                                    id="start-station", # Original ID
                                                                    options=[],
                                                                    placeholder="Select Station...",
                                                                    className="mb-3",
                                                                    persistence = True,
                                                                    persistence_type = 'session'
                                                                )
                                                            ], width=6),

                                                            dbc.Col([
                                                                html.Label("End Station", className="criteria-label"),
                                                                dcc.Dropdown(
                                                                    id="end-station", # Original ID
                                                                    options=[],
                                                                    placeholder="Select Station...",
                                                                    className="mb-3",
                                                                )
                                                            ], width=6),
                                                        ], className="gx-2"),

                                                        # Intermediate Stations full width below
                                                        html.Label("Passing Through", className="criteria-label"),
                                                        dcc.Dropdown(
                                                            id="intermediate-stations", # Original ID
                                                            options=[],
                                                            multi=True,
                                                            placeholder="Add intermediate stations",
                                                            className="mb-3",
                                                        ),
                                                        html.Label("In time period", className="criteria-label"),
                                                        dcc.RangeSlider(
                                                            id="time-range-slider", # Original ID
                                                            min=0,
                                                            max=1440,
                                                            step=15,
                                                            value=[165, 1605],
                                                            marks={
                                                                i: f"{(i // 60):02d}:{(i % 60):02d}" for i in range(0, 1441, 120)
                                                            },
                                                            tooltip={"placement": "bottom", "always_visible": False},
                                                            allowCross=False,
                                                        ),
                                                    ])
                                                ],
                                                className="criteria-card mb-4",
                                                style={"margin": "0px 0px"}
                                            )
                                        ),

                                        # --- TAB 2: SERVICE FILTERS (New IDs) ---
                                        dbc.Tab(
                                            label="Services",
                                            tab_id="tab-service",
                                            children=dbc.Card(
                                                [
                                                    dbc.CardBody([
                                                        # RE-ID'd components for Services
                                                        dbc.Row([
                                                            dbc.Col([
                                                                html.Label("Start Station", className="criteria-label"),
                                                                dcc.Dropdown(id="start-station_service", # New ID
                                                                            options=[],
                                                                            placeholder="Select Station..."),
                                                            ], width=6),
                                                            dbc.Col([
                                                                html.Label("End Station", className="criteria-label"),
                                                                dcc.Dropdown(id="end-station_service", # New ID
                                                                            options=[],
                                                                            placeholder="Select Station..."),
                                                            ], width=6),
                                                        ], className="gx-2"),
                                                        html.Div([
                                                            html.Label("Passing Through", className="criteria-label me-2"),

                                                            # --- Dropdown + Toggles in same line ---
                                                            html.Div([
                                                                dcc.Dropdown(
                                                                    id="intermediate-stations_service",
                                                                    options=[],
                                                                    multi=True,
                                                                    placeholder="Add intermediate stations",
                                                                    style={"flex": "1"},
                                                                ),

                                                                # Toggle buttons inline to the right of dropdown
                                                                html.Div([
                                                                    # html.Label("Direction", className="criteria-label me-2"),
                                                                    dbc.Checklist(
                                                                        options=[
                                                                            {"label": "UP", "value": "UP"},
                                                                            {"label": "DOWN", "value": "DOWN"},
                                                                        ],
                                                                        value=["UP", "DOWN"],  # default both selected
                                                                        id="direction-selector",
                                                                        inline=True,
                                                                        switch=True,
                                                                        className="ms-3 mb-0",  # spacing between dropdown and toggles
                                                                    )
                                                                ])
                                                            ], className="d-flex align-items-center gap-2 mb-3", style={"width": "100%"}),
                                                        ]),
                                                        html.Label("In time period", className="criteria-label"),
                                                        dcc.RangeSlider(
                                                            id="time-range-slider_service", # New ID
                                                            min=0,
                                                            max=1440,
                                                            step=15,
                                                            value=[165, 1605],
                                                            marks={
                                                                i: f"{(i // 60):02d}:{(i % 60):02d}" for i in range(0, 1441, 120)
                                                            },
                                                            tooltip={"placement": "bottom", "always_visible": False},
                                                            allowCross=False,
                                                        ),
                                                        
                                                    
                                                        # html.Label("Service Type", className="criteria-label", style={"marginTop": "16px"}),
                                                        # dbc.RadioItems(
                                                        #     id="service-type-radio",
                                                        #     options=[
                                                        #         {"label": "All", "value": "all"},
                                                        #         {"label": "Fast", "value": "fast"},
                                                        #         {"label": "Slow", "value": "slow"},
                                                        #     ],
                                                        #     value="all",
                                                        #     inline=True,
                                                        #     inputStyle={"marginRight": "6px"},
                                                        #     labelStyle={"marginRight": "12px", "fontSize": "13px"},
                                                        # )
                                                    ])
                                                ],
                                                className="criteria-card mb-4",
                                                style={"margin": "0px 0px"}
                                            )
                                        ),

                                        dbc.Tab(label="Stations",
                                                tab_id="tab-station",
                                                children=dbc.Card(
                                                    [dbc.CardBody([
                                                        html.Label("In time period", className="criteria-label"),
                                                        dcc.RangeSlider(
                                                            id="time-range-slider_station", # New ID
                                                            min=0,
                                                            max=1440,
                                                            step=15,
                                                            value=[165, 1605],
                                                            marks={
                                                                i: f"{(i // 60):02d}:{(i % 60):02d}" for i in range(0, 1441, 120)
                                                            },
                                                            tooltip={"placement": "bottom", "always_visible": False},
                                                            allowCross=False,
                                                        ),
                                                    ])]
                                                ))
                                    ],
                                    className="mb-4" # Add margin to separate from Generate button
                                )
                            ], style={"position": "relative"}),

                            # Generate button
                            html.Div(
                                [
                                    html.Button(
                                        "Generate",
                                        id="generate-button",
                                        n_clicks=0,
                                        className="generate-button",
                                        disabled=True,
                                    )
                                ],
                                style={"padding": "0px 35px"}  # Match other elements
                            ),
                        ],
                        className="four columns sidebar",
                    ),

                    # === RIGHT PANEL ===
                    dcc.Store(id="graph-ready", data=False),
                    html.Div(
                        [
                            html.Div(id="status-div", className="text-box"),

                            # === PILL TOGGLE + EXPORT BUTTON ROW ===
                            html.Div(
                                [
                                    dbc.ButtonGroup(
                                        [
                                            dbc.Button("Visualization", id="mode-viz", color="primary", outline=True, active=True),
                                            dbc.Button("Query Info", id="mode-details", color="primary", outline=True, active=False),
                                        ],
                                        size="sm",
                                        className="mode-pill-toggle",
                                        style={"marginLeft": "20px"} 
                                    ),
                                            html.Div(
            dbc.Button(
                "Convert to AC",
                id="convert-ac-button",
                color="primary",
                outline=True,
                disabled=True,
            ),
            style={"marginLeft": "auto", "marginRight": "8px"}
        ),
        html.Div(
        dbc.Button(
            "Reset",
            id="reset-ac-button",
            color="warning",
            outline=True,
            size="sm",
        ),
        style={"marginLeft": "4px", "display": "None"}
        ),

                                    html.Div(
                                        dbc.Button(
                                            "Export Summary",
                                            id="export-button",
                                            color="secondary",
                                            outline=True,
                                            disabled=True,
                                        ),
                                        className="ms-auto",  # push to right
                                    ),
                                ],
                                className="d-flex align-items-center justify-content-between mb-2",
                            ),

                            dcc.Download(id="download-report"),

                            # ---- DYNAMIC CONTENT ----
                            html.Div(
                                id="viz-container",
                                children=[
                                    dcc.Graph(id="rake-3d-graph", style={"height": "65vh"}),
                                    html.Div(
                                        id="rake-link-table-container",
                                        children = [
                                            # html.Hr(style={"margin": "20px 0 10px 0"}),
                                            html.Div(
                                                id="rake-link-count",
                                                style={"marginBottom": "6px", "fontWeight": "500"}
                                            ),

                                            dash_table.DataTable(
                                                id="rake-link-table",
                                                columns=[
                                                    {"name": "Link", "id": "linkname"},
                                                    {"name": "Cars", "id": "cars"},
                                                    {"name": "AC?", "id": "is_ac"},
                                                    {"name": "Length (km)", "id": "length_km"},
                                                    {"name": "Start", "id": "start"},
                                                    {"name": "End", "id": "end"},
                                                    {"name": "#Svcs", "id": "n_services"},
                                                ],
                                                data=[],
                                                row_selectable="multi",
                                                selected_rows=[],
                                                page_size=45,
                                                sort_action="native",
                                                filter_action="native",
                                                style_table={"maxHeight": "260px", "overflowY": "auto"},
                                                style_cell={"padding": "6px", "fontSize": "13px"},
                                            )
                                        ],
                                        style={"padding": "10px 0px"}
                                    ),

# Add a new table that appears ONLY in service mode
html.Div(
    id="service-table-container",
    children=[
        html.Hr(),
        html.Div(
            id="service-count",
            style={"marginBottom": "6px", "fontWeight": "500"}
        ),
        dash_table.DataTable(
            id="service-table",
            columns=[
                {"name": "Service ID", "id": "service_id"},
                {"name": "Direction", "id": "direction"},
                {"name": "AC?", "id": "is_ac"},
                {"name": "Cars", "id": "cars"},
                {"name": "Start", "id": "start_station"},
                {"name": "End", "id": "end_station"},
                {"name": "Start Time", "id": "start_time"},
                {"name": "Rake Link", "id": "rake_link"},
            ],
            data=[],
            row_selectable="multi",
            selected_rows=[],
            page_size=45,
            sort_action="native",
            filter_action="native",
            style_table={"maxHeight": "260px", "overflowY": "auto"},
            style_cell={"padding": "6px", "fontSize": "13px"},
        )
    ],
    style={"padding": "10px 0px", "display": "none"}  # Hidden by default
)

                                    # html.Div(
                                    #     "Click 'Generate' to build visualization.",
                                    #     style={
                                    #         "position": "absolute",
                                    #         "top": "50%",
                                    #         "left": "50%",
                                    #         "transform": "translate(-50%, -50%)",
                                    #         "color": "#888",
                                    #         "fontSize": "18px",
                                    #         "display": "block"
                                    #     },
                                    # )
                                ],
                                style={"position": "relative", "height": "75vh"}
                            ),

                            html.Div(id="right-panel-content", style={"marginTop": "10px"}),
                        ],
                        className="eight columns",
                        id="page",
                    ),


                ],
                className="row flex-display",
                style={"height": "100vh"},
            )


    def convertRakeLinksToAC(self, link_names):
        """
        Convert specified rake links to AC.
        Updates both Rake and Service objects.
        
        Args:
            link_names: List of rake link names (e.g., ['A', 'B'])
        
        Returns:
            dict with conversion summary
        """
        if not link_names:
            return {"converted": 0, "links": []}
        
        converted = []
        
        for rc in self.parser.wtt.rakecycles:
            if rc.linkName in link_names:
                # Skip if already AC
                if rc.rake and rc.rake.isAC:
                    continue
                
                # Convert the rake
                if rc.rake:
                    rc.rake.isAC = True
                
                # Convert all services in this rake cycle
                for svc in rc.servicePath:
                    svc.needsACRake = True
                
                converted.append(rc.linkName)
        
        return {
            "converted": len(converted),
            "links": converted
        }

    def initCallbacks(self):
        self._initFileUploadCallbacks()
        self._initButtonCallbacks()
        self._initFilterQueryCallbacks() 

    def _is_valid_xlsx(self, filename):
        return bool(filename) and filename.lower().endswith(".xlsx")

    def _initFilterQueryCallbacks(self):
        '''Each UI filter updates self.query attributes directly.'''

        # ---------------------------------------------------------------------
        # Helper: handles both rakelink, service and station inputs in one place
        # ---------------------------------------------------------------------
        def _update_query_field(ctx, field, value_rakelink, value_service=None, value_station=None):
            '''Update a FilterQuery field depending on which input triggered.'''
            if not ctx.triggered:
                return None
            trigger = ctx.triggered[0]['prop_id'].split('.')[0]

            # Choose correct source
            if trigger.endswith('_service'):
                setattr(self.query, field, value_service)
            elif trigger.endswith('_station'):
                setattr(self.query, field, value_station)
            else:
                setattr(self.query, field, value_rakelink)
            return None

        @self.app.callback(
            Input('start-station', 'value'),
            Input('start-station_service', 'value'),
        )
        def update_start_station(value_rakelink, value_service):
            return _update_query_field(callback_context, 'startStation', value_rakelink, value_service)

        @self.app.callback(
            Input('end-station', 'value'),
            Input('end-station_service', 'value'),
        )
        def update_end_station(value_rakelink, value_service):
            return _update_query_field(callback_context, 'endStation', value_rakelink, value_service)

        @self.app.callback(
            Input('intermediate-stations', 'value'),
            Input('intermediate-stations_service', 'value'),
        )
        def update_passing_through(value_rakelink, value_service):
            v1 = value_rakelink or []
            v2 = value_service or []
            return _update_query_field(callback_context, 'passingThrough', v1, v2)

        @self.app.callback(
            Input('time-range-slider', 'value'),
            Input('time-range-slider_service', 'value'),
            Input('time-range-slider_station', 'value'),
            prevent_initial_call=False
        )
        def update_time_period(value_rakelink, value_service, value_station):
            return _update_query_field(callback_context, 'inTimePeriod', value_rakelink, value_service, value_station)

        @self.app.callback(
            Input('ac-selector', 'value'),
        )
        def update_ac_filter(value_rakelink):
            return _update_query_field(callback_context, 'ac', value_rakelink)

        @self.app.callback(
            Input('direction-selector', 'value'),
        )
        def update_service_direction(value):
            self.query.inDirection = value
            return None

        @self.app.callback(
            Input('filter-tabs', 'active_tab'),
            State('time-range-slider', 'value'),
            State('time-range-slider_service', 'value'),
            State('time-range-slider_station', 'value'),
        )
        def update_query_type(active_tab, rk_time, svc_time, st_time):
            # Update filter type
            if active_tab == "tab-rakelink":
                self.query.type = FilterType.RAKELINK
                self.query.inTimePeriod = rk_time          # ← RESET TIME
                self.query.inDirection = None

            elif active_tab == "tab-service":
                self.query.type = FilterType.SERVICE
                self.query.inTimePeriod = svc_time         # ← RESET TIME

            elif active_tab == "tab-station":
                self.query.type = FilterType.STATION
                self.query.inTimePeriod = st_time          # ← RESET TIME

            return None

        @self.app.callback(
            Output('app-state', 'data', allow_duplicate=True),
            Input('filter-tabs', 'active_tab'),
            prevent_initial_call=True 
        )
        def update_query_type(active_tab):
            # Save current filter state
            if self.query.type:
                self.filterStates[self.query.type] = {
                    'startStation': self.query.startStation,
                    'endStation': self.query.endStation,
                    'passingThrough': self.query.passingThrough.copy(),
                    'inTimePeriod': self.query.inTimePeriod,
                    'inDirection': self.query.inDirection,
                }
            
            # Update type
            if active_tab == "tab-rakelink":
                self.query.type = FilterType.RAKELINK
            elif active_tab == "tab-service":
                self.query.type = FilterType.SERVICE
            elif active_tab == "tab-station":
                self.query.type = FilterType.STATION
            
            # Restore saved state for new tab
            saved = self.filterStates.get(self.query.type, {})
            self.query.startStation = saved.get('startStation')
            self.query.endStation = saved.get('endStation')
            self.query.passingThrough = saved.get('passingThrough', [])
            self.query.inTimePeriod = saved.get('inTimePeriod', (165, 1605))
            self.query.inDirection = saved.get('inDirection')
            
            return None
        
    def _initFileUploadCallbacks(self):
        '''Handle file uploads and update UI'''
        @self.app.callback(
            Output('upload-wtt-inline', 'children'),
            Output('upload-wtt-inline', 'style'),
            Input('upload-wtt-inline', 'contents'),
            State('upload-wtt-inline', 'filename')
        )
        def update_wtt_filename(contents, filename):
            base_style = {
                "height": "140px",
                "borderWidth": "2px",
                "borderStyle": "dashed",
                "borderRadius": "12px",
                "borderColor": "#cbd5e1",
                "display": "flex",
                "alignItems": "center",
                "justifyContent": "center",
                "cursor": "pointer",
                "transition": "all 0.2s ease",
            }
            if contents is None:
                return html.Div([
                    html.Img(src="/assets/excel-icon.png",
                            style={"width": "28px", "height": "28px", "marginBottom": "6px"}),
                    html.Div("Full WTT",
                            style={"fontWeight": "500", "color": "#334155", "fontSize": "14px"}),
                    html.Div("Click to upload",
                            style={"fontSize": "11px", "color": "#94a3b8", "marginTop": "4px"})
                ], className="text-center"), base_style

            # When uploaded
            self.wttContents = contents
            self.wttFileName = filename
            display_name = filename if len(filename) <= 40 else filename[:37] + "..."
            
            success_style = copy.deepcopy(base_style)
            success_style.update({
                "borderStyle": "solid",
                "borderColor": "#188038",  # Google Sheets green
            })
            
            return html.Div([
                html.Img(src="/assets/excel-icon.png",
                        style={"width": "24px", "height": "24px", "marginBottom": "4px"}),
                html.Div(display_name,
                        style={"fontSize": "11px", "color": "#188038", "fontWeight": "500", "wordBreak": "break-all"})
            ], className="text-center"), success_style

        @self.app.callback(
            Output('upload-summary-inline', 'children'),
            Output('upload-summary-inline', 'style'),
            Input('upload-summary-inline', 'contents'),
            State('upload-summary-inline', 'filename')
        )
        def update_summary_filename(contents, filename):            
            base_style = {
                "height": "140px",
                "borderWidth": "2px",
                "borderStyle": "dashed",
                "borderRadius": "12px",
                "borderColor": "#cbd5e1",
                "display": "flex",
                "alignItems": "center",
                "justifyContent": "center",
                "cursor": "pointer",
                "transition": "all 0.2s ease",
            }
            if contents is None:
                return html.Div([
                    html.Img(src="/assets/excel-icon.png",
                            style={"width": "28px", "height": "28px", "marginBottom": "6px"}),
                    html.Div("WTT Link Summary",
                            style={"fontWeight": "500", "color": "#334155", "fontSize": "14px"}),
                    html.Div("Click to upload",
                            style={"fontSize": "11px", "color": "#94a3b8", "marginTop": "4px"})
                ], className="text-center"), base_style
            
            self.summaryContents = contents
            self.summaryFileName = filename
            # Truncate long filenames
            display_name = filename if len(filename) <= 40 else filename[:37] + "..."
            
            success_style = copy.deepcopy(base_style)
            success_style.update({
                "borderStyle": "solid",
                "borderColor": "#188038",  # Google Sheets green
            })
            
            return html.Div([
                html.Img(src="/assets/excel-icon.png",
                        style={"width": "24px", "height": "24px", "marginBottom": "4px"}),
                html.Div(display_name,
                        style={"fontSize": "11px", "color": "#188038", "fontWeight": "500", "wordBreak": "break-all"})
            ], className="text-center"), success_style

        @self.app.callback(
            Output('generate-button', 'disabled'),
            Output('generate-button', 'style'),
            [Input('upload-wtt-inline', 'contents'),
            Input('upload-summary-inline', 'contents')]
        )
        def enable_generate_button(wtt_contents, summary_contents):
            '''Enable button only when both files are uploaded'''
            base_style = {
                "border": "none",
                "width": "100%",
                "height": "42px",
                "borderRadius": "8px",
                # "border": "dashed",
                "fontWeight": "600",
                "fontSize": "14px",
                "cursor": "pointer",
                "transition": "all 0.2s ease",
            }

            if wtt_contents is not None and summary_contents is not None:
                # Both uploaded → enable + green border
                enabled_style = base_style | {
                    # "border": "2px solid #188038",
                    # "backgroundColor": "white",
                    # "color": "#188038",
                    "opacity":"1",
                }
                return False, enabled_style
            else:
                # Default → disabled grayish border
                disabled_style = base_style | {
                    # "border": "2px solid #cbd5e1",
                    # "backgroundColor": "#f1f5f9",
                    "color": "#94a3b8",
                    # "cursor": "not-allowed",
                    "cursor": "not-allowed",
                    "opacity": "0.65",
                }
                return True, disabled_style

        @self.app.callback(
            [Output('start-station', 'disabled'),
            Output('end-station', 'disabled'),
            Output('intermediate-stations', 'disabled'),
            Output('time-range-slider', 'disabled'),
            Output('filter-overlay', 'style')],
            [Input('upload-wtt-inline', 'contents'),
            Input('upload-summary-inline', 'contents')]
        )
        def toggle_filters(wtt_contents, summary_contents):
            '''Enable filters only when both files are uploaded'''
            if wtt_contents is not None and summary_contents is not None:
                # Both uploaded -> enable filters
                overlay_style = {"display": "none"}
                return False, False, False, False, overlay_style
            else:
                # Not uploaded -> disable filters
                overlay_style = {
                    "position": "absolute",
                    "top": "0",
                    "left": "0",
                    "right": "0",
                    "bottom": "0",
                    "backgroundColor": "rgba(243, 246, 250, 0.7)",
                    "zIndex": "10",
                    "cursor": "not-allowed",
                    "borderRadius": "12px"
                }
                return True, True, True, True, overlay_style
        
        @self.app.callback(
            [Output('app-state', 'data'),
            Output('start-station', 'options'),
            Output('end-station', 'options'),
            Output('intermediate-stations', 'options'),
            Output('start-station_service', 'options'),
            Output('end-station_service', 'options'),
            Output('intermediate-stations_service', 'options')],  
            Input('upload-wtt-inline', 'contents')
        )
        def initFilters(wttContents):
            if not self._is_valid_xlsx(self.wttFileName):
                raise PreventUpdate
            if not wttContents:
                return None,[],[],[],[],[],[] # should never reach here
            
            wttDecoded = base64.b64decode(wttContents.split(',')[1])
            wttIO = io.BytesIO(wttDecoded)

            if not self.parser:
                self.parser = tt.TimeTableParser()

            # register stations
            self.parser.xlsxToDfFromFileObj(wttIO)
            self.parser.registerStations()

            stations = [s for s in self.parser.wtt.stations]
            options = [{"label": s, "value": s} for s in stations]

            return {"initialized": True}, options, options, options, options, options, options


        @self.app.callback(
            [Input('upload-wtt-inline', 'contents'),
            Input('upload-summary-inline', 'contents')],
            prevent_initial_call=True
        )
        def initBackend(wttContents, summaryContents):
            if wttContents is None and summaryContents is None:
                return

            if not (
                self._is_valid_xlsx(self.wttFileName)
                and self._is_valid_xlsx(self.summaryFileName)
            ):
                raise PreventUpdate
            
            try:
                summaryDecoded = base64.b64decode(summaryContents.split(',')[1])
                summaryIO = io.BytesIO(summaryDecoded)
                
                self.parser.registerServices()
                self.parser.parseWttSummaryFromFileObj(summaryIO)
                self.parser.wtt.suburbanServices = self.parser.isolateSuburbanServices()
            
            except Exception as e:
                print(f"Error initializing backend: {e}")
                return 

    def _initButtonCallbacks(self): 
        @self.app.callback(
            Output('rake-3d-graph', 'figure', allow_duplicate=True),
            Output('rake-link-table', 'data', allow_duplicate=True),
            Output('status-div', 'children', allow_duplicate=True),
            Input('reset-ac-button', 'n_clicks'),
            State('rake-3d-graph', 'figure'),
            prevent_initial_call=True
        )
        def reset_ac_conversions(n_clicks, current_fig):
            """Reset all AC conversions to original state from data"""
            if not n_clicks:
                raise PreventUpdate
            
            # Re-parse data to restore original state
            # You'll need to store original AC status or re-read from files
            # For now, just show message
            status_msg = html.Div(
                "Reset functionality requires storing original state",
                style={"padding": "8px", "color": "#f59e0b"}
            )
            
            raise PreventUpdate  # Implement full reset logic as needed
        @self.app.callback(
            Output('convert-ac-button', 'disabled'),
            Input('rake-link-table', 'selected_rows'),
            Input("filter-tabs", "active_tab"),
            State('rake-link-table', 'data'),
            prevent_initial_call=True
        )
        def toggle_convert_button(selected_rows, active_tab, table_data):
            """Enable Convert to AC button only when non-AC links are selected in rakelink mode"""
            if active_tab != "tab-rakelink" or not selected_rows or not table_data:
                return True
            
            # Check if any selected link is non-AC
            has_nonac = False
            for idx in selected_rows:
                if idx < len(table_data):
                    if table_data[idx]["is_ac"] == "Non-AC":
                        has_nonac = True
                        break
            
            return not has_nonac  # Enable if we have at least one non-AC link

        @self.app.callback(
            Output('rake-3d-graph', 'figure', allow_duplicate=True),
            Output('rake-link-table', 'data', allow_duplicate=True),
            Output('status-div', 'children', allow_duplicate=True),
            Input('convert-ac-button', 'n_clicks'),
            State('rake-link-table', 'selected_rows'),
            State('rake-link-table', 'data'),
            State('rake-3d-graph', 'figure'),
            prevent_initial_call=True
        )
        def handle_ac_conversion(n_clicks, selected_rows, table_data, current_fig):
            """Convert selected rake links to AC and update visualization"""
            if not n_clicks or not selected_rows or not table_data:
                raise PreventUpdate
            
            # Get selected link names
            selected_links = [
                table_data[idx]["linkname"] 
                for idx in selected_rows 
                if idx < len(table_data)
            ]
            
            # Perform conversion
            result = self.convertRakeLinksToAC(selected_links)
            
            # Update table data (mark converted links as AC)
            updated_table = table_data.copy()
            for row in updated_table:
                if row["linkname"] in result["links"]:
                    row["is_ac"] = "AC"
            
            # Regenerate visualization with updated data
            self._reset_render_flags()
            self._apply_filters(self.query)
            fig = self.visualizeLinks3D()
            fig = self._post_process_station_mode(fig, self.query)
            
            # Re-apply highlighting if there were selections
            if self.query.selectedLinks:
                self._highlight_clicked(fig, self.query.selectedLinks)
            
            # Status message
            status_msg = html.Div(
                [
                    # html.Span("✓ ", style={"color": "#10b981", "fontWeight": "600"}),
                    html.Span(f"Converted {result['converted']} rake link(s) to AC: "),
                    html.Span(", ".join(result["links"]), style={"fontWeight": "500"})
                ],
                style={
                    "padding": "8px 12px",
                    # "backgroundColor": "#d1fae5",
                    "borderLeft": "3px solid #10b981",
                    "borderRadius": "4px",
                    "marginBottom": "8px"
                }
            )
            
            return fig, updated_table, status_msg

        @self.app.callback(
            Output("rake-link-table-container", "style"),  
            Output("service-table-container", "style"),
            Input("filter-tabs", "active_tab"),
            Input("graph-ready", "data")
        )
        def toggle_table_display(active_tab, graph_ready):
            if not graph_ready:
                return {"display": "none"}, {"display": "none"}
            
            if active_tab == "tab-service":
                # Hide rake table, show service table
                return {"display": "none"}, {"padding": "10px 0px", "display": "block"}
            else:
                # Show rake table, hide service table (default for rake-link and station modes)
                return {"padding": "10px 0px", "display": "block"}, {"display": "none"}       
        
        @self.app.callback(
            Output('rake-3d-graph', 'figure', allow_duplicate=True),
            Input('service-table', 'selected_rows'),
            State('rake-3d-graph', 'figure'),
            State('service-table', 'data'),
            State("filter-tabs", "active_tab"),
            prevent_initial_call=True
        )
        def update_graph_from_service_selection(selected_rows, current_fig, table_data, active_tab):
            if active_tab != "tab-service" or current_fig is None or not current_fig.get('data'):
                raise PreventUpdate
            
            # Extract selected service IDs
            if not selected_rows or not table_data:
                selected_services = []
            else:
                selected_services = [
                    table_data[idx]["service_id"] 
                    for idx in selected_rows 
                    if idx < len(table_data)
                ]
            
            # Update query state
            self.query.selectedServices = selected_services
            
            # Apply highlighting
            fig = go.Figure(current_fig)
            self._highlight_clicked_services(fig, selected_services)
            
            return fig

        @self.app.callback(
            Output("service-table", "selected_rows"),
            Input("rake-3d-graph", "clickData"),
            State("service-table", "data"),
            State("service-table", "selected_rows"),
            State("filter-tabs", "active_tab"),
            prevent_initial_call=True,
        )
        def toggle_service_from_graph(clickData, table_rows, current_selection, active_tab):
            if active_tab != "tab-service" or not clickData or not table_rows:
                return current_selection or []
            
            try:
                # Extract service ID from hover text
                # Format is "LinkName-ServiceID: Station @ Time"
                hover_text = clickData["points"][0].get("hovertext", "")
                
                # Parse "A-93001: VIRAR @ 02:45" → "93001"
                parts = hover_text.split(':')[0].strip()  # "A-93001"
                if '-' in parts:
                    clicked_service = parts.split('-')[1]  # "93001"
                else:
                    return current_selection or []
                
            except (KeyError, IndexError) as e:
                print(f"Error extracting clicked service: {e}")
                return current_selection or []
            
            # Find row index for this service
            clicked_idx = None
            for idx, row in enumerate(table_rows):
                if clicked_service in row.get("service_id", ""):
                    clicked_idx = idx
                    break
            
            if clicked_idx is None:
                return current_selection or []
            
            # Toggle selection
            selected = list(current_selection or [])
            if clicked_idx in selected:
                selected.remove(clicked_idx)
            else:
                selected.append(clicked_idx)
            
            return selected
            
        @self.app.callback(
            Output('rake-3d-graph', 'figure', allow_duplicate=True),
            Input('rake-link-table', 'selected_rows'),
            State('rake-3d-graph', 'figure'),
            State('rake-link-table', 'data'),
            prevent_initial_call=True
        )
        def update_graph_highlighting(selected_rows, current_fig, table_data):
            """Update graph highlighting when selection changes without regenerating the entire plot"""
            if current_fig is None or not current_fig.get('data'):
                raise PreventUpdate
            
            # Extract selected link names
            if not selected_rows or not table_data:
                selected_links = []
            else:
                selected_links = [
                    table_data[idx]["linkname"] 
                    for idx in selected_rows 
                    if idx < len(table_data)
                ]
            
            # Update the query state
            self.query.selectedLinks = selected_links
            
            # Apply highlighting to the existing figure
            fig = go.Figure(current_fig)
            self._highlight_clicked(fig, selected_links)
            
            return fig 

        @self.app.callback(
            Output("service-table", "data"),
            Output("service-count", "children"),
            Input('generate-button', 'n_clicks'),
            Input('ac-selector', 'value'),
            State("filter-tabs", "active_tab"),
            prevent_initial_call=True
        )
        def build_service_table(n_clicks, ac_select, active_tab):
            is_service_mode = (
                active_tab == "tab-service" or 
                self.query.type == FilterType.SERVICE
            )

            if n_clicks == 0 or self.parser is None or not is_service_mode:
                return [], ""
            
            rows = []
            for svc in self.parser.wtt.suburbanServices:
                if not svc.render or not svc.events:
                    continue
                
                # Get service details
                svc_id_str = ','.join(str(sid) for sid in svc.serviceId)
                start_time = fmt_time(svc.events[0].atTime) if svc.events else "--:--"
                
                # Find which rake link this service belongs to
                rake_link = "?"
                for rc in self.parser.wtt.rakecycles:
                    if svc in rc.servicePath:
                        rake_link = rc.linkName
                        break
                
                rows.append({
                    "id": svc_id_str,  # Used for selection tracking
                    "service_id": svc_id_str,
                    "direction": svc.direction.name if svc.direction else "?",
                    "is_ac": "AC" if svc.needsACRake else "Non-AC",
                    "cars": svc.rakeSizeReq if svc.rakeSizeReq else "?",
                    "start_station": svc.initStation.name if svc.initStation else "?",
                    "end_station": svc.finalStation.name if svc.finalStation else "?",
                    "start_time": start_time,
                    "rake_link": rake_link,
                })
            
            return rows, f"{len(rows)} services"
        
        @self.app.callback(
            Output("rake-link-table", "data"),
            Output("rl-table-store", "data"),
            Output("rake-link-count", "children"),
            Input('generate-button', 'n_clicks'),
            Input('ac-selector', 'value'),
            State('upload-wtt-inline', 'contents'),
            State('upload-summary-inline', 'contents'),
            prevent_initial_call=True
        )
        def build_rake_table(n_clicks, ac_select, wttContents, summaryContents):
            time.sleep(2)
            if n_clicks == 0 or self.parser is None:
                return [], [], ""

            rows = []
            for rc in self.parser.wtt.rakecycles:
                if not rc.render or rc.rake is None:
                    continue

                rows.append({
                    "id": rc.linkName,
                    "linkname": rc.linkName,
                    "cars": rc.rake.rakeSize,
                    "is_ac": "AC" if rc.rake.isAC else "Non-AC",
                    "length_km": int(rc.lengthKm),
                    "start": rc.servicePath[0].initStation.name,
                    "end": rc.servicePath[-1].finalStation.name,
                    "n_services": len(rc.servicePath),
                })

            return rows, rows, f"{len(rows)} rake links"

        @self.app.callback(
            Output("right-panel-content", "children", allow_duplicate=True),
            Input('rake-link-table', 'selected_rows'),
            State("mode-details", "active"),
            prevent_initial_call=True
        )
        def update_query_info_on_selection(selected_rows, details_active):
            """Update Query Info panel content when selection changes, but only if already viewing it"""
            if not details_active:
                # Don't update if we're not viewing Query Info
                raise PreventUpdate
            
            # We're viewing Query Info, so update it
            return self.build_query_info_panel()

        @self.app.callback(
            Output("rake-link-table", "selected_rows"),
            Input("rake-3d-graph", "clickData"),
            State("rake-link-table", "data"),
            State("rake-link-table", "selected_rows"),
            prevent_initial_call=True,
        )
        def toggle_row_from_graph(clickData, table_rows, current_selection):
            """Add/remove clicked trace from selection"""
            if not clickData or not table_rows:
                return current_selection or []
            
            # Get clicked link name from the trace
            try:
                # The trace name is stored in the 'name' property of the clicked point's trace
                curve_number = clickData["points"][0].get("curveNumber")
                # We need to get the actual trace name from the figure, but we can't access it here
                # Instead, use hovertext which contains the link name
                hover_text = clickData["points"][0].get("hovertext", "")
                
                # Format is "LinkName: Station @ Time" or "LinkName-ServiceID: Station @ Time"
                clicked_link = hover_text.split(':')[0].strip()
                
                # Handle service-level traces (format: "A-93001" -> "A")
                clicked_link = clicked_link.split('-')[0]
                
                print(f"Clicked link from graph: {clicked_link}")
                
            except (KeyError, IndexError) as e:
                print(f"Error extracting clicked link: {e}")
                return current_selection or []
            
            # Find row index for this link
            clicked_idx = None
            for idx, row in enumerate(table_rows):
                if row.get("linkname") == clicked_link:
                    clicked_idx = idx
                    break
            
            if clicked_idx is None:
                print(f"Link {clicked_link} not found in table")
                return current_selection or []
            
            # Toggle: add if not present, remove if present
            selected = list(current_selection or [])
            if clicked_idx in selected:
                selected.remove(clicked_idx)
                print(f"Removed {clicked_link} from selection")
            else:
                selected.append(clicked_idx)
                print(f"Added {clicked_link} to selection")
            
            return selected
        

        @self.app.callback(
            Output('app-state', 'data', allow_duplicate=True),  # Reuse existing store
            Input('rake-link-table', 'selected_rows'),
            State('rake-link-table', 'data'),
            prevent_initial_call=True
        )
        def update_selected_rakes(selected_rows, table_data):
            """Update self.query.selectedLinks when table selection changes"""
            if not selected_rows or not table_data:
                self.query.selectedLinks = []
                return {"selectedLinks": []}
            
            # Extract link names from selected rows
            selected_links = [
                table_data[idx]["linkname"] 
                for idx in selected_rows 
                if idx < len(table_data)
            ]
            
            self.query.selectedLinks = selected_links
            return {"selectedLinks": selected_links}

        @self.app.callback(
            Output("viz-container", "style"),
            Output("right-panel-content", "children"),
            Output("mode-viz", "active"),
            Output("mode-details", "active"),
            Input("mode-viz", "n_clicks"),
            Input("mode-details", "n_clicks"),
            # REMOVED: Input('rake-link-table', 'selected_rows')  <-- This was the problem!
        )
        def switch_right_panel(viz_clicks, details_clicks):
            ctx = dash.callback_context.triggered_id
            
            # Only switch when buttons are clicked, NOT when selection changes
            if ctx == "mode-details":
                return {"display": "none"}, self.build_query_info_panel(), False, True

            # Default: show visualization
            return {"display": "block"}, html.Div(), True, False
           
        @self.app.callback(
            Output('status-div', 'children'),
            Output('rake-3d-graph', 'figure'),
            Output('export-button', 'disabled'),
            Output("graph-ready", "data"),
            Output("rake-link-table", "selected_rows", allow_duplicate=True),  
            Output("service-table", "selected_rows", allow_duplicate=True),    
            Input('generate-button', 'n_clicks'),
            Input('rake-3d-graph', 'clickData'),
            Input('ac-selector', 'value'),
            State('upload-wtt-inline', 'contents'),
            State('upload-summary-inline', 'contents'),
            prevent_initial_call=True
        )
        def onGenerateClick(n_clicks, clickData, ac_status, wttContents, summaryContents):

            if n_clicks == 0 or wttContents is None or summaryContents is None:
                return "", go.Figure(), True, False, [], []

            try:
                # Sync AC filter
                self.query.ac = ac_status

                self.query.selectedLinks = []
                self.query.selectedServices = []
                qq = self.query

                # First-time backend build
                if not self.linkTimingsCreated:
                    self.parser.wtt.generateRakeCycles()
                    self.parser.wtt.storeOriginalACStates() 
                    self.linkTimingsCreated = True
                else:
                    self.parser.wtt.resetACStates()

                # Reset all state
                self._reset_render_flags()

                # Apply filters
                self._apply_filters(qq)

                # Generate base plot
                fig = self.visualizeLinks3D()

                # Station mode post-processing
                fig = self._post_process_station_mode(fig, qq)

                if self.query.selectedLinks:
                    self._highlight_clicked(fig, self.query.selectedLinks)

                # Handle clicking a rake-link trace
                # ctx = callback_context
                # trigger = ctx.triggered[0]["prop_id"]
                # if trigger == "rake-3d-graph.clickData" and qq.type == FilterType.RAKELINK:

                #     if not clickData or "points" not in clickData or not clickData["points"]:
                #         print("Reset: empty or invalid clickData")
                #         for rc in self.parser.wtt.rakecycles:
                #             rc.render = True
                #         fig.update_layout(annotations=[])
                #         return "", fig, False, True  # FIX: Return 4 values

                #     p = clickData["points"][0]
                #     idx = p.get("curveNumber")
                #     if idx is None or idx >= len(fig.data):
                #         fig = self._reset_isolation(fig)
                #         return "", fig, False, True

                #     clicked = fig.data[idx].name
                #     print("Clicked Rake Link:", clicked)

                #     # Update render state
                #     for rc in self.parser.wtt.rakecycles:
                #         rc.render = (rc.linkName == clicked)

                #     # Highlight traces
                #     self._highlight_clicked(fig, clicked)

                #     # Annotation
                #     rc = next(r for r in self.parser.wtt.rakecycles if r.linkName == clicked)
                    # fig.update_layout(annotations=self._build_annotation(rc))

                    # return html.Div(), fig, False, True

                # Default final return
                return html.Div(), fig, False, True, [], []

            except Exception as e:
                import traceback
                traceback.print_exc()
                return (html.Div(f"Error: {e}"), go.Figure(), True, False, [], [])

    
        @self.app.callback(
                Output('download-report', 'data'),
                Input('export-button', 'n_clicks'),
                prevent_initial_call=True
        )
        def trigger_download(n_clicks):
            filter_type = self.query.type.value if self.query.type else "unknown"
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
            filename = f"wtt_report_{filter_type}_{timestamp}.txt"
            filename_xlsx = f"WTT_Export_{filter_type}_{timestamp}.xlsx"

            # Use dcc.send_data_frame to export to Excel
            report_xlsx = self.exportXlsx()
            return dcc.send_data_frame(report_xlsx.to_excel, filename_xlsx, index=False)
            
            # report_content = self.exportResults() 
            
            # return dict(content=report_content, filename=filename)
        
        
    def detectGaps(self, size, stations, inTime):
        print(f"# Gaps > {size} minutes:")
        t_lower, t_upper = inTime

        for stn in stations:
            events = tt.TimeTableParser.eventsByStationMap.get(stn, [])
            if not events:
                print(f"{stn}: 0")
                continue

            # collect only times inside the given range
            times = [e.atTime for e in events if t_lower <= e.atTime <= t_upper]

            if not times:
                print(f"{stn}: 0")
                continue

            times.sort()

            gapCount = 0
            for i in range(1, len(times)):
                if (times[i] - times[i-1]) > size:
                    gapCount += 1

            print(f"{stn}: {gapCount}")


    def applyStationFilters(self, qq):
        t_lower, t_upper = qq.inTimePeriod
        for rc in self.parser.wtt.rakecycles:
            rc.render = True

        for svc in self.parser.wtt.suburbanServices:
            svc.render = True

            # FIX: Check if events exist before accessing
            if not svc.events:
                svc.render = False
                continue

            for ev in svc.events:
                ev.render = True
                
                # FIX: Check if atTime exists
                if ev.atTime is None:
                    ev.render = False
                    continue
                    
                t = ev.atTime
                if not (t_lower <= t <= t_upper):
                    ev.render = False
            
            svc.checkACConstraint(qq)

        

    def applyServiceFilters(self, qq):
        '''
        Filters individual services based on the Service tab query constraints.
        Sets the 'render' flag on each Service object.
        Also updates the parent RakeCycle 'render' flag.
        '''
        for svc in self.parser.wtt.suburbanServices:
            svc.render = True

            if not svc.events: # invalid
                svc.render = False
                continue
            # Also reset event render flags
            for ev in svc.events:
                ev.render = True

            # check if the service satisfies the 
            # start and end station constraint
            svc.checkDirectionConstraint(qq)
            svc.checkACConstraint(qq)
            svc.checkStartStationConstraint(qq)
            svc.checkEndStationConstraint(qq)
            svc.checkPassingThroughConstraint(qq)
            print(f"constraint checks done for {svc}")
        # print("all services constraint checks done")
        
        for rc in self.parser.wtt.rakecycles:
            rc.render = False
            if rc.servicePath:
                if any(svc.render for svc in rc.servicePath):
                    rc.render = True
        
        visible_services = len([s for s in self.parser.wtt.suburbanServices if s.render])
        visible_cycles = len([r for r in self.parser.wtt.rakecycles if r.render])
        # print(f"Visible services after filter: {visible_services}")
        # print(f"Visible rake cycles after filter: {visible_cycles}")

    def exportXlsx(self):
        """
        Generates a Pandas DataFrame containing the filtered services with 
        columns for Direction, Line, Service ID, Stations, and Timings.
        """
        rows = []
        
        # Collect services based on the current filter/render state
        # Usually, self.parser.wtt.suburbanServices contains all services
        for svc in self.parser.wtt.suburbanServices:
            if not getattr(svc, 'render', True):
                continue
                
            # Formatting Departure and Arrival
            # Departure is the first event, Arrival is the last event
            dep_time = "--:--"
            arr_time = "--:--"
            if svc.events:
                dep_time = fmt_time(svc.events[0].atTime)
                arr_time = fmt_time(svc.events[-1].atTime)

            # Determine Line (Fast/Slow)
            # Typically Line.THROUGH is Fast and Line.LOCAL is Slow
            line_str = "Fast" if svc.line == tt.Line.THROUGH else "Slow"

            rows.append({
                "Service ID": ", ".join(str(sid) for sid in svc.serviceId),
                "Start Time": dep_time,
                "Source": svc.initStation.name,
                "Destination": svc.finalStation.name,
                "Direction": svc.direction.name,   # UP or DOWN
                "Line": line_str,                  # Fast or Slow
            })

        return pd.DataFrame(rows)
            
    def exportResults(self):
            buffer = io.StringIO() # Use StringIO to capture print output

            # print the query
            buffer.write(f"Filter Query: {self.query}\n\n")
            
            # list rakecycle inconsistencies
            buffer.write("=== Rake Link Inconsistencies ===\n")
            if self.parser.wtt.conflictingLinks:
                for el in self.parser.wtt.conflictingLinks:
                    buffer.write(f"Link {el[0].linkName}")
                    buffer.write(f"  Summary: {el[0].serviceIds}\n")
                    buffer.write(f"  WTT:     {el[1]}\n---\n")
            else:
                buffer.write("  No inconsistencies found.\n")


            if self.query.type == FilterType.RAKELINK:
                # List rakecycles plotted
                buffer.write("\n=== Rake Links Plotted (RakeLink Filter) ===\n")
                plotted_rcs = [rc for rc in self.parser.wtt.rakecycles if rc.render]
                if plotted_rcs:
                    for rc in plotted_rcs:
                        buffer.write(f"{rc}\n")
                        buffer.write(f"Services: {rc.serviceIds}\n")
                else:
                    buffer.write("  No rake links matched the filter criteria.\n")

            
            if self.query.type == FilterType.SERVICE:
                # List rake links with their rendered services
                buffer.write("\n=== Rake Links with Rendered Services (Service Filter) ===\n")
                any_rendered = False
                for rc in self.parser.wtt.rakecycles:
                    if not rc.render:
                        continue
                        
                    # Get rendered services in this rake cycle
                    rendered_services = [svc for svc in rc.servicePath if svc.render]
                    
                    if rendered_services:
                        any_rendered = True
                        buffer.write(f"\n{rc}\n")
                        buffer.write(f"  Rendered Services ({len(rendered_services)}/{len(rc.servicePath)}):\n")
                        for svc in rendered_services:
                            buffer.write(f"    {svc}\n")
                
                if not any_rendered:
                    buffer.write("  No services matched the filter criteria.\n")
            
                # === Passing Through Times (sorted) ===
                if self.query.passingThrough:
                    buffer.write("\n=== Passing Through Times (Grouped by Station, Sorted by Time) ===\n")

                    pt_stations = [s.upper() for s in self.query.passingThrough]

                    # Filter services passing all constraints
                    rendered_services = [
                        svc for svc in self.parser.wtt.suburbanServices
                        if getattr(svc, "render", False)
                    ]

                    if not rendered_services:
                        buffer.write("  No services matched the filter criteria.\n\n")
                    else:
                        # Build: station list of (serviceId, time_minutes, time_str)
                        st_table = {st: [] for st in pt_stations}

                        for svc in rendered_services:
                            sid = svc.serviceId[0]

                            # Map events for this service
                            st_times = {}
                            for ev in svc.events:
                                if not getattr(ev, "render", True):
                                    continue
                                st = ev.atStation.upper()
                                st_times.setdefault(st, []).append(ev.atTime)

                            # Fill table
                            for st in pt_stations:
                                if st in st_times:
                                    t = st_times[st][-1]   # last occurrence as you defined
                                    hh = int(t // 60)
                                    mm = int(t % 60)
                                    time_str = f"{hh:02d}:{mm:02d}"
                                    st_table[st].append((sid, t, time_str))
                                else:
                                    # No pass — push with None time so it sorts last
                                    st_table[st].append((sid, None, "---"))

                        # Sort each station’s list by time (None goes last)
                        for st in pt_stations:
                            st_table[st].sort(key=lambda x: (x[1] is None, x[1]))

                        # Print nicely
                        for st in pt_stations:
                            buffer.write(f"\n=== {st} ===\n")
                            for sid, t, time_str in st_table[st]:
                                buffer.write(f"   {sid:<8} {time_str}\n")

                        buffer.write("\n")

            return buffer.getvalue() # Return the string content

            
    def make_summary_card(self, title, items, footer=None):
        '''Reusable helper to build a clean, minimal summary card.'''
        return dbc.Card(
            [
                dbc.CardHeader(
                    html.Strong(title, style={"fontSize": "14px", "color": "#1e293b"}),
                    style={
                        "backgroundColor": "#f8fafc",
                        "borderBottom": "1px solid #e2e8f0",
                        "padding": "6px 10px"
                    }
                ),
                dbc.CardBody(
                    [
                        html.Ul(
                            [html.Li(i, style={"marginBottom": "4px"}) for i in items],
                            style={
                                "paddingLeft": "18px",
                                "margin": "0",
                                "fontSize": "13px",
                                "color": "#334155",
                                "listStyleType": "disc"
                            }
                        )
                    ],
                    style={"padding": "10px 12px"}
                ),
                dbc.CardFooter(
                    footer if footer else "",
                    style={
                        "backgroundColor": "#fafafa",
                        "borderTop": "1px solid #e2e8f0",
                        "fontSize": "12px",
                        "color": "#64748b",
                        "padding": "6px 10px"
                    }
                ) if footer else None
            ],
            style={
                "borderRadius": "8px",
                "border": "1px solid #e2e8f0",
                "boxShadow": "0 1px 2px rgba(0,0,0,0.04)",
                "backgroundColor": "white",
                "height": "100%"
            }
        )


    def generateSummaryStatus(self):
        wtt = self.parser.wtt

        # compute stats
        rcs = [rc for rc in wtt.rakecycles if rc.render]

        # total services
        total_services=0
        ac_services=0
        for rc in rcs:
            total_services += len(rc.servicePath)
            for svc in rc.servicePath:
                if svc.needsACRake and svc.render:
                    ac_services+=1
                    # print(f"Needs AC: {svc.serviceId}")
                # else:
                #     print(f"Non AC: {svc.serviceId}")

        total_parsed_services = len(wtt.suburbanServices) 
        non_ac_services = total_services - ac_services 

        # rake links
        total_parsed_links = len(wtt.rakecycles)
        parsing_conflicts = len(wtt.conflictingLinks)

        total_rendered_links = len(rcs)
        valid_rcs = [rc for rc in rcs if rc.lengthKm > 0]
        shortest_rcs = sorted(valid_rcs, key=lambda rc:rc.lengthKm)[:3]
        longest_rcs = sorted(valid_rcs, key=lambda rc: rc.lengthKm, reverse=True)[:3]

        # contents
        svcs = [s for s in wtt.suburbanServices if s.render]
        if self.query.type == FilterType.SERVICE:
            total_services = len(svcs)
            non_ac_services = total_services - ac_services

        service_items = [
            f"Total Parsed services: {total_parsed_services}",
            f"Rendered Services: {total_services}",
            f"AC services: {ac_services}",
            f"Non-AC services: {non_ac_services}",
        ]

        rake_items = [
            f"Total parsed rake links: {total_parsed_links}",
            f"Parsing Conflicts: {parsing_conflicts}",
            f"Rendered Links: {total_rendered_links}",
        ]

        rake_footer = html.Div([
            html.Small("Shortest: " + ", ".join(f"{rc.linkName} ({rc.lengthKm:.1f} km)" for rc in shortest_rcs)),
            html.Br(),
            html.Small("Longest: " + ", ".join(f"{rc.linkName} ({rc.lengthKm:.1f} km)" for rc in longest_rcs)),
        ])

        service_card = self.make_summary_card("Service Summary", service_items)
        rake_card = self.make_summary_card("Rake Link Summary", rake_items, footer=rake_footer)

        #htnl 
        summary_layout = dbc.Row(
            [
                dbc.Col(service_card, width=6, style={"padding": "4px"}),
                dbc.Col(rake_card, width=6, style={"padding": "4px"})
            ],
            className="g-1",  # minimal gap between cols
            style={"margin": "0"}
        )

        # Outer wrapper
        return html.Div(
            summary_layout,
            style={
                "margin": "0px 0px 0px 0px",
                "padding": "0px 4px",
                "borderRadius": "6px",
                "backgroundColor": "#f9fafb"
            }
        )

            
    def applyTerminalStationFilters(self, start, end):
        print(f"Applying filters: start={start}, end={end}")

        for rc in self.parser.wtt.rakecycles:
            rc.render = True  # reset all first
            if not rc.servicePath:
                rc.render = False
                continue

            first = rc.servicePath[0].events[0].atStation
            last = rc.servicePath[-1].events[-1].atStation
            # print(f"is {end} == {last}")

            if start and start.upper() != first:
                rc.render = rc.render and False
            if end and end.upper() != last:
                rc.render = rc.render and False
            # else:
            #     print(f"Match! {rc.linkName}")
    
    def applyPassingThroughFilter(self, qq):
        '''Make rakecycles visible that have events at every station in passingThru within the specified timeperiod'''
        selected = qq.passingThrough
        print(qq.passingThrough)
        if not selected:
            return
        
        selected = [s.upper() for s in selected]
        t_start, t_end = qq.inTimePeriod if qq.inTimePeriod else (None, None)

        for rc in self.parser.wtt.rakecycles:
            rc.render = rc.render and True
            if not rc.servicePath:
                rc.render = rc.render and False
                continue

            # flatten all events in this rakecycle
            el = []
            for s in rc.servicePath:
                el.extend(s.events)

            # filter by time
            if qq.inTimePeriod:
                filtered = []
                for e in el:
                    if not e.atTime:
                        continue

                    minutes = e.atTime

                    if t_start <= minutes <= t_end:
                        filtered.append(e)
                el = filtered  # keep only events inside window

            # station membership check
            seen = set()
            for e in el:
                if not e.atStation:
                    continue
                stName = str(e.atStation).strip().upper()
                if stName in selected:
                    seen.add(stName)
                if len(seen) == len(selected):
                    break

            if len(seen) < len(selected):
                rc.render = False

    def applyACFilter(self, qq):
        '''Render only AC / Non-AC / All rake cycles as per filter.'''
        mode = qq.ac
        if mode is None or mode == "all":
            return  # no filtering

        for rc in self.parser.wtt.rakecycles:
            # rc.render = True
            if not rc.rake:
                rc.render = False
                continue

            if mode == "ac" and not rc.rake.isAC:
                rc.render = False
            elif mode == "nonac" and rc.rake.isAC:
                rc.render = False

    def applyLinkFilters(self, qq):
        '''Filter rake cycles based on selected start and end stations.'''

        self.applyTerminalStationFilters(qq.startStation, qq.endStation)
        self.applyPassingThroughFilter(qq)
        self.applyACFilter(qq)

        visible_count = len([r for r in self.parser.wtt.rakecycles if r.render])
        print(f"Visible rake cycles after filter: {visible_count}")

    def visualizeLinks3D(self):
        rakecycles = [rc for rc in self.parser.wtt.rakecycles if rc.servicePath]
        print(f"We have  len {len(rakecycles)}")
        if not rakecycles:
            raise ValueError("No valid rakecycles found.")

        distanceMap = tt.TimeTableParser.distanceMap
        stationToY = {st.upper(): distanceMap[st.upper()] for st in distanceMap}

        all_traces = []
        z_labels = []
        z_offset = 0

        # Check if we're filtering by service (granular) or rake link (coarse)
        is_service_filter = (self.query.type == FilterType.SERVICE)

        for rc in rakecycles:
            # --- SERVICE FILTER MODE: Only render filtered services ---
            if is_service_filter:
            # Don't check rc.render here - we only care about individual services
                for svc in rc.servicePath:
                    # Skip services that don't pass the filter
                    if not svc.render:
                        continue

                    # Build points for this single service
                    # Separate lists for in-range vs out-of-range events
                    x_in, y_in, z_in, labels_in = [], [], [], []
                    x_out, y_out, z_out, labels_out = [], [], [], []
                    
                    for ev in svc.events:
                        # if not ev.atTime or not ev.atStation:
                        #     continue

                        minutes = ev.atTime

                        stName = str(ev.atStation).strip().upper()
                        if stName not in stationToY:
                            continue

                        # # Check if event is within the filtered time range
                        # ev_render = getattr(ev, 'render', True)
                        
                        # if ev_render:
                        # Event is in the time filter range
                        x_in.append(minutes)
                        y_in.append(stationToY[stName])
                        z_in.append(z_offset)
                        labels_in.append(stName)
                        # else:
                        #     # Event is outside the time filter range
                        #     x_out.append(minutes)
                        #     y_out.append(stationToY[stName])
                        #     z_out.append(z_offset)
                        #     labels_out.append(stName)

                    # Format service IDs for display (handle list of IDs)
                    svc_id_str = ','.join(str(sid) for sid in svc.serviceId) if svc.serviceId else '?'
                    
                    # Create trace for OUT-OF-RANGE events (dimmed, background context)
                    if x_out:
                        color_dim = "rgba(66,133,244,0.6)" if svc.needsACRake else "rgba(90,90,90,0.6)"
                        
                        all_traces.append(
                            go.Scatter3d(
                                x=x_out, y=y_out, z=z_out,
                                mode="lines+markers",
                                line=dict(color=color_dim),
                                marker=dict(size=2, color=color_dim),
                                hovertext=[
                                    f"{svc_id_str}: {st} @ {(int(xx)//60) % 24:02d}:{int(xx%60):02d} (outside filter)"
                                    for xx, st in zip(x_out, labels_out)
                                ],
                                hoverinfo="text",
                                name=f"{rc.linkName}-{svc_id_str} (context)",
                                showlegend=False,  # Don't clutter legend with dimmed traces
                                visible=True,
                            )
                        )
                    
                    # Create trace for IN-RANGE events (prominent, filtered results)
                    # color = "rgba(66,133,244,0.8)" if svc.needsACRake else "rgba(90,90,90,0.8)"
                    if x_in:
                        color_bright = "rgba(66,133,244,0.8)" if svc.needsACRake else "rgba(90,90,90,0.8)"
                        
                        all_traces.append(
                            go.Scatter3d(
                                x=x_in, y=y_in, z=z_in,
                                mode="lines+markers",
                                line=dict(color=color_bright),
                                marker=dict(size=2, color=color_bright),  # Larger markers
                                hovertext=[
                                    f"{svc_id_str}: {st} @ {(int(xx)//60) % 24:02d}:{int(xx%60):02d}"
                                    for xx, st in zip(x_in, labels_in)
                                ],
                                hoverinfo="text",
                                name=f"{rc.linkName}-{svc_id_str}",
                                visible=True,
                            )
                        )
                        z_labels.append((z_offset, f"{rc.linkName}-{svc_id_str}"))
                    
                    # Only increment z if we rendered something
                    if x_in or x_out:
                        z_offset += 40  # increment z for next service

            # RAKELINK mode
            else:
                # Check if this rake cycle passes the rake link filters
                if not rc.render:
                    continue

                if self.query.type == FilterType.STATION:
                    mode = "markers"
                elif self.query.type ==FilterType.RAKELINK:
                    mode = "lines+markers"
                
                # Aggregate all services in the rake cycle into a single trace
                x, y, z, stationLabels = [], [], [], []

                for svc in rc.servicePath:
                    if not svc.render:
                        continue
                    # In rake link mode, we render all services in a visible rake cycle
                    for ev in svc.events:
                        if not ev.atTime or not ev.atStation:
                            continue

                        if not ev.render:
                            continue
                            
                        minutes = ev.atTime
                        # print(minutes)

                        stName = str(ev.atStation).strip().upper()
                        if stName not in stationToY:
                            continue

                        x.append(minutes)
                        y.append(stationToY[stName])
                        z.append(z_offset)
                        stationLabels.append(stName)
                
                # Create single trace for entire rake cycle
                if x:
                    color = "rgba(66,133,244,0.8)" if rc.rake.isAC else "rgba(90,90,90,0.8)"
                    
                    all_traces.append(
                        go.Scatter3d(
                            x=x, y=y, z=z,
                            mode=mode,
                            line=dict(color=color),
                            marker=dict(size=2, color=color),
                            # customdata=[{"link": rc.linkName} for _ in x],
                            hovertext=[
                                f"{rc.linkName}: {st} @ {(int(xx)//60) % 24:02d}:{int(xx%60):02d}"
                                for xx, st in zip(x, stationLabels)
                            ],

                            hoverinfo="text",
                            name=rc.linkName,
                            visible=True,
                        )
                    )
                    z_labels.append((z_offset, rc.linkName))
                    z_offset += 40  # increment z for next rakecycle
        
        if self.query.inTimePeriod and (self.query.type == FilterType.SERVICE or 
                                        self.query.type == FilterType.STATION):
            x_start, x_end = self.query.inTimePeriod
            x_end += 90 # padding
        else:
            x_start, x_end  = 165, 1605
        # padding = 120  # 120 minutes
        # x_end = (x_end + padding)
        # x_start = max(0, x_start - padding)

        tickPositions = list(range(x_start, x_end + 1, 120))
        tickLabels = [f"{(t // 60) % 24:02d}:{int(t % 60):02d}" for t in tickPositions]

        yTickVals = list(stationToY.values())
        yTickText = list(stationToY.keys())

        fig = go.Figure(data=all_traces)

        fig.update_layout(
            font=dict(size=12, color="#CCCCCC"),
            scene=dict(
                xaxis=dict(
                    showgrid=True,
                    showspikes=False,
                    title="Time of Day →",
                    range=[x_start, x_end],
                    tickvals=tickPositions,
                    ticktext=tickLabels,
                ),
                yaxis=dict(
                    showgrid=True,
                    showspikes=False,
                    title="",
                    tickvals=yTickVals,
                    ticktext=yTickText,
                    range=[min(yTickVals), max(yTickVals)],
                    autorange=False
                ),
                zaxis=dict(
                    showgrid=True,
                    showspikes=False,
                    title="Service" if is_service_filter else "Rake Cycle",
                    tickvals=[zv for zv, _ in z_labels],
                    ticktext=[zl for _, zl in z_labels],
                ),
                camera=dict(
                    eye=dict(x=0, y=0, z=2.5),
                    up=dict(x=0, y=1, z=0),
                    center=dict(x=0, y=0, z=0)
                ),
                aspectmode="manual",
                aspectratio=dict(x=2.8, y=1.2, z=1.2)
            ),
            scene_camera_projection_type="orthographic",
            width=1300,
            height=700,
            margin=dict(t=0, l=5, b=5, r=5),
            autosize=True
        )

        return fig

    def run(self):
        self.app.run(debug=True, port=8051)

if __name__ == "__main__":
    sim = Simulator()
    sim.run()
