import plotly.graph_objects as go
import numpy as np
import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State


# ==============================================================================
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: матрица поворота e_z → n
# ==============================================================================

def _rotation_to(n):
    u_z = np.array([0., 0., 1.])
    v = np.cross(u_z, n)
    s = np.linalg.norm(v)
    c = np.dot(u_z, n)
    if s < 1e-9:
        return np.sign(c) * np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * ((1 - c) / (s ** 2))


def _abs_surface():
    phi_s = np.linspace(0, 2 * np.pi, 50)
    theta_s = np.linspace(0, np.pi, 50)
    return (np.outer(np.cos(phi_s), np.sin(theta_s)),
            np.outer(np.sin(phi_s), np.sin(theta_s)),
            np.outer(np.ones_like(phi_s), np.cos(theta_s)))


# ==============================================================================
# ВКЛАДКА 1: ГИПЕРБОЛИЧЕСКАЯ СФЕРА
# ==============================================================================

def create_sphere_figure(radius_hs, center_x, center_y, center_z, show_axes=True):
    r = 1.0
    center_hs = np.array([center_x, center_y, center_z])
    fig = go.Figure()

    xa, ya, za = _abs_surface()
    phi_surf = np.linspace(0, 2 * np.pi, 50)
    theta_surf = np.linspace(0, np.pi, 50)
    fig.add_trace(go.Surface(x=xa, y=ya, z=za,
                             colorscale='Blues', opacity=0.15, showscale=False,
                             name='Абсолют', hoverinfo='none'))

    dist_from_origin = np.linalg.norm(center_hs)
    is_sphere = dist_from_origin < 1e-6

    if is_sphere:
        x_hs = center_hs[0] + radius_hs * np.outer(np.cos(phi_surf), np.sin(theta_surf))
        y_hs = center_hs[1] + radius_hs * np.outer(np.sin(phi_surf), np.sin(theta_surf))
        z_hs = center_hs[2] + radius_hs * np.outer(np.ones_like(phi_surf), np.cos(theta_surf))
        R = np.eye(3)
        radius_parallel = radius_perp = radius_hs
    else:
        squash_factor = np.sqrt(max(1.0 - dist_from_origin ** 2, 1e-9))
        radius_parallel = radius_hs * squash_factor
        radius_perp = radius_hs
        x_ell_std = radius_perp * np.outer(np.cos(phi_surf), np.sin(theta_surf))
        y_ell_std = radius_perp * np.outer(np.sin(phi_surf), np.sin(theta_surf))
        z_ell_std = radius_parallel * np.outer(np.ones_like(phi_surf), np.cos(theta_surf))
        R = _rotation_to(center_hs / dist_from_origin)
        coords = np.vstack([x_ell_std.ravel(), y_ell_std.ravel(), z_ell_std.ravel()])
        rotated_coords = R @ coords
        x_hs = rotated_coords[0].reshape(x_ell_std.shape) + center_hs[0]
        y_hs = rotated_coords[1].reshape(y_ell_std.shape) + center_hs[1]
        z_hs = rotated_coords[2].reshape(z_ell_std.shape) + center_hs[2]

    fig.add_trace(go.Surface(x=x_hs, y=y_hs, z=z_hs,
                             colorscale='Greens', opacity=0.6, showscale=False,
                             name='Гиперболическая сфера', hoverinfo='none'))
    fig.add_trace(go.Scatter3d(x=[center_hs[0]], y=[center_hs[1]], z=[center_hs[2]],
                               mode='markers', marker=dict(color='black', size=5, symbol='diamond'),
                               name='Центр', hoverinfo='none', showlegend=True))

    num_lines = 50
    indices = np.arange(0, num_lines, dtype=float) + 0.5
    phi_dirs = np.arccos(1 - 2 * indices / num_lines)
    theta_dirs = np.pi * (1 + 5 ** 0.5) * indices

    for i in range(num_lines):
        d = np.array([np.cos(theta_dirs[i]) * np.sin(phi_dirs[i]),
                      np.sin(theta_dirs[i]) * np.sin(phi_dirs[i]),
                      np.cos(phi_dirs[i])])
        b2 = 2 * np.dot(center_hs, d)
        c2 = np.dot(center_hs, center_hs) - r ** 2
        disc = b2 ** 2 - 4 * c2
        if disc < 0:
            continue
        t_m = (-b2 - np.sqrt(disc)) / 2
        t_p = (-b2 + np.sqrt(disc)) / 2
        p1 = center_hs + t_m * d
        p2 = center_hs + t_p * d
        vec = p2 - p1
        if np.linalg.norm(vec) < 1e-6:
            continue

        D_inv = np.diag([1 / radius_perp ** 2, 1 / radius_perp ** 2, 1 / radius_parallel ** 2])
        M_inv = R @ D_inv @ R.T
        oc = p1 - center_hs
        a_e = vec @ M_inv @ vec
        b_e = 2 * (vec @ M_inv @ oc)
        c_e = oc @ M_inv @ oc - 1
        disc_e = b_e ** 2 - 4 * a_e * c_e

        if disc_e < 0:
            fig.add_trace(go.Scatter3d(x=[p1[0], p2[0]], y=[p1[1], p2[1]], z=[p1[2], p2[2]],
                                       mode='lines', line=dict(color='#C80000', width=2),
                                       showlegend=False, hoverinfo='none'))
            continue

        t_en = (-b_e - np.sqrt(disc_e)) / (2 * a_e)
        t_ex = (-b_e + np.sqrt(disc_e)) / (2 * a_e)
        pe = p1 + t_en * vec
        px = p1 + t_ex * vec

        if t_en > 1e-6:
            fig.add_trace(go.Scatter3d(x=[p1[0], pe[0]], y=[p1[1], pe[1]], z=[p1[2], pe[2]],
                                       mode='lines', line=dict(color='#C80000', width=2),
                                       showlegend=False, hoverinfo='none'))
        if (t_ex - t_en) * np.linalg.norm(vec) > 1e-6:
            fig.add_trace(go.Scatter3d(x=[pe[0], px[0]], y=[pe[1], px[1]], z=[pe[2], px[2]],
                                       mode='lines', line=dict(color='#C80000', width=1.5, dash='dash'),
                                       showlegend=False, hoverinfo='none'))
        if 1 - t_ex > 1e-6:
            fig.add_trace(go.Scatter3d(x=[px[0], p2[0]], y=[px[1], p2[1]], z=[px[2], p2[2]],
                                       mode='lines', line=dict(color='#C80000', width=2),
                                       showlegend=False, hoverinfo='none'))

    if show_axes:
        al = r * 1.1
        for ax, col, lbl in [([- al, al], [0, 0], [0, 0], 'red', 'X'),
                              ([0, 0], [-al, al], [0, 0], 'blue', 'Y'),
                              ([0, 0], [0, 0], [-al, al], 'green', 'Z')]:
            pass
        for xs, ys, zs, col, lbl in [
            ([-al, al], [0, 0], [0, 0], 'red', 'X'),
            ([0, 0], [-al, al], [0, 0], 'blue', 'Y'),
            ([0, 0], [0, 0], [-al, al], 'green', 'Z'),
        ]:
            fig.add_trace(go.Scatter3d(x=xs, y=ys, z=zs, mode='lines',
                                       line=dict(color=col, width=2), showlegend=False, hoverinfo='none'))
            fig.add_trace(go.Scatter3d(
                x=[xs[-1] * 1.05], y=[ys[-1] * 1.05], z=[zs[-1] * 1.05],
                mode='text', text=[lbl], textfont=dict(color=col, size=14),
                showlegend=False, hoverinfo='none'))

    fig.update_layout(
        uirevision='constant',
        title='Гиперболическая сфера в модели Бельтрами-Клейна',
        scene=dict(xaxis=dict(visible=False), yaxis=dict(visible=False),
                   zaxis=dict(visible=False), aspectmode='data'),
        margin=dict(l=0, r=0, b=0, t=40),
        legend=dict(x=0.8, y=0.9),
        font=dict(family="Arial, sans-serif", size=12, color="black")
    )
    return fig


# ==============================================================================
# ВКЛАДКА 2: ОРИСФЕРА
# ==============================================================================

def create_orosphere_figure(phi, theta, r_horo, show_guiding_lines=True):
    omega = np.array([np.sin(phi) * np.cos(theta),
                      np.sin(phi) * np.sin(theta),
                      np.cos(phi)])
    center_horo = (1.0 - r_horo) * omega

    fig = go.Figure()
    xa, ya, za = _abs_surface()
    phi_surf = np.linspace(0, 2 * np.pi, 50)
    theta_surf = np.linspace(0, np.pi, 50)

    fig.add_trace(go.Surface(x=xa, y=ya, z=za,
                             colorscale='Blues', opacity=0.15, showscale=False,
                             name='Абсолют', hoverinfo='none'))
    fig.add_trace(go.Surface(
        x=center_horo[0] + r_horo * np.outer(np.cos(phi_surf), np.sin(theta_surf)),
        y=center_horo[1] + r_horo * np.outer(np.sin(phi_surf), np.sin(theta_surf)),
        z=center_horo[2] + r_horo * np.outer(np.ones_like(phi_surf), np.cos(theta_surf)),
        colorscale='Oranges', opacity=0.6, showscale=False, name='Орисфера', hoverinfo='none'))
    fig.add_trace(go.Scatter3d(x=[omega[0]], y=[omega[1]], z=[omega[2]],
                               mode='markers', marker=dict(color='purple', size=7, symbol='diamond'),
                               name='Идеальная точка ω', hoverinfo='none'))

    if show_guiding_lines:
        indices = np.arange(0, 30, dtype=float) + 0.5
        phi_d = np.arccos(1 - 2 * indices / 30)
        theta_d = np.pi * (1 + 5 ** 0.5) * indices
        for i in range(30):
            p = np.array([np.cos(theta_d[i]) * np.sin(phi_d[i]),
                          np.sin(theta_d[i]) * np.sin(phi_d[i]),
                          np.cos(phi_d[i])])
            if np.linalg.norm(p - omega) < 0.2:
                continue
            fig.add_trace(go.Scatter3d(x=[omega[0], p[0]], y=[omega[1], p[1]], z=[omega[2], p[2]],
                                       mode='lines', line=dict(color='#8B4513', width=1.5),
                                       showlegend=False, hoverinfo='none'))

    fig.update_layout(
        uirevision='constant',
        title='Орисфера в модели Бельтрами-Клейна',
        scene=dict(xaxis=dict(visible=False), yaxis=dict(visible=False),
                   zaxis=dict(visible=False), aspectmode='data'),
        margin=dict(l=0, r=0, b=0, t=40),
        legend=dict(x=0.8, y=0.9),
        font=dict(family="Arial, sans-serif", size=12, color="black")
    )
    return fig


# ==============================================================================
# ВКЛАДКА 3: ЭКВИДИСТАНТА (третий тип пучков)
# ==============================================================================
# В модели Бельтрами-Клейна эквидистанта от геодезической плоскости
# (диска z'=0 в повёрнутой системе) на гиперболическом расстоянии h —
# это поверхность z' = ±√(1−x'²−y'²)·tanh(h).
# Это точная формула, выводимая через формулу кросс-отношения.

def create_equidistant_figure(phi, theta, h, show_plane=True):
    n = np.array([np.sin(phi) * np.cos(theta),
                  np.sin(phi) * np.sin(theta),
                  np.cos(phi)])
    R = _rotation_to(n)

    fig = go.Figure()
    xa, ya, za = _abs_surface()
    fig.add_trace(go.Surface(x=xa, y=ya, z=za,
                             colorscale='Blues', opacity=0.15, showscale=False,
                             name='Абсолют', hoverinfo='none'))

    # Геодезическая плоскость — плоский диск
    rho = np.linspace(0, 0.999, 30)
    alpha = np.linspace(0, 2 * np.pi, 60)
    RHO, ALPHA = np.meshgrid(rho, alpha)
    disk_local = np.vstack([(RHO * np.cos(ALPHA)).ravel(),
                            (RHO * np.sin(ALPHA)).ravel(),
                            np.zeros(RHO.size)])
    disk_w = R @ disk_local
    if show_plane:
        fig.add_trace(go.Surface(
            x=disk_w[0].reshape(RHO.shape),
            y=disk_w[1].reshape(RHO.shape),
            z=disk_w[2].reshape(RHO.shape),
            colorscale='Greys', opacity=0.3, showscale=False,
            name='Геодезическая плоскость', hoverinfo='none'))

    # Эквидистанта: z' = ±√(1−ρ²)·tanh(h)
    tanh_h = np.tanh(h)
    rho_e = np.linspace(0, 0.999, 60)
    alpha_e = np.linspace(0, 2 * np.pi, 60)
    RHO_E, ALPHA_E = np.meshgrid(rho_e, alpha_e)
    x_e = RHO_E * np.cos(ALPHA_E)
    y_e = RHO_E * np.sin(ALPHA_E)
    z_base = np.sqrt(np.maximum(1 - RHO_E ** 2, 0)) * tanh_h

    for sign, name_e, cscale in [(1, 'Эквидистанта (+h)', 'Reds'),
                                  (-1, 'Эквидистанта (−h)', 'Reds')]:
        coords_e = np.vstack([x_e.ravel(), y_e.ravel(), (sign * z_base).ravel()])
        w = R @ coords_e
        fig.add_trace(go.Surface(
            x=w[0].reshape(x_e.shape), y=w[1].reshape(x_e.shape), z=w[2].reshape(x_e.shape),
            colorscale=cscale, opacity=0.55, showscale=False, name=name_e, hoverinfo='none'))

    # Перпендикулярные геодезические (пучок ультрапараллельных прямых)
    n_g = 25
    idx = np.arange(n_g, dtype=float) + 0.5
    r_g = np.sqrt(idx / n_g) * 0.85
    th_g = np.pi * (1 + 5 ** 0.5) * idx
    for i in range(n_g):
        a, b = r_g[i] * np.cos(th_g[i]), r_g[i] * np.sin(th_g[i])
        z_end = np.sqrt(max(1 - a ** 2 - b ** 2, 0))
        p1 = R @ np.array([a, b, -z_end])
        p2 = R @ np.array([a, b, z_end])
        fig.add_trace(go.Scatter3d(x=[p1[0], p2[0]], y=[p1[1], p2[1]], z=[p1[2], p2[2]],
                                   mode='lines', line=dict(color='#006400', width=1),
                                   showlegend=False, hoverinfo='none'))

    fig.update_layout(
        uirevision='constant',
        title='Эквидистанта в модели Бельтрами-Клейна',
        scene=dict(xaxis=dict(visible=False), yaxis=dict(visible=False),
                   zaxis=dict(visible=False), aspectmode='data'),
        margin=dict(l=0, r=0, b=0, t=40),
        legend=dict(x=0.8, y=0.9),
        font=dict(family="Arial, sans-serif", size=12, color="black")
    )
    return fig


# ==============================================================================
# ПРИЛОЖЕНИЕ DASH
# ==============================================================================

app = dash.Dash(__name__)

SLIDER_STYLE = {'marginTop': '10px', 'display': 'block'}
PANEL_STYLE = {'flexShrink': '0', 'width': '300px', 'padding': '20px',
               'border': '1px solid #ccc', 'borderRadius': '8px'}
GRAPH_STYLE = {'flexGrow': '1', 'height': '70vh', 'width': 'auto'}
ROW_STYLE = {'display': 'flex', 'flexDirection': 'row', 'justifyContent': 'center',
             'alignItems': 'flex-start', 'gap': '20px', 'marginTop': '20px'}
BTN_STYLE = {'marginTop': '16px', 'display': 'block', 'margin': '16px auto 0', 'padding': '10px 20px'}

PI_MARKS = {round(v, 2): s for v, s in
            [(0, '0'), (np.pi / 4, 'π/4'), (np.pi / 2, 'π/2'),
             (3 * np.pi / 4, '3π/4'), (np.pi, 'π')]}
TAU_MARKS = {round(v, 2): s for v, s in
             [(0, '0'), (np.pi / 2, 'π/2'), (np.pi, 'π'),
              (3 * np.pi / 2, '3π/2'), (2 * np.pi, '2π')]}

tab_sphere = dcc.Tab(label='Гиперболическая сфера', value='sphere', children=[
    html.Div([
        html.Button('Скрыть/показать оси XYZ', id='toggle-axes-button', n_clicks=0, style=BTN_STYLE),
        dcc.Store(id='axes-visibility-store', data={'visible': True}),
    ], style={'textAlign': 'center'}),
    html.Div(style=ROW_STYLE, children=[
        dcc.Graph(id='hyperbolic-sphere-graph', style=GRAPH_STYLE),
        html.Div(style=PANEL_STYLE, children=[
            html.Label("Центр X", style={'marginTop': '0', 'display': 'block'}),
            dcc.Slider(id='center-x-slider', min=-0.6, max=0.6, step=0.05, value=0.2,
                       marks={i / 10: str(i / 10) for i in range(-6, 7, 2)}),
            html.Label("Центр Y", style=SLIDER_STYLE),
            dcc.Slider(id='center-y-slider', min=-0.6, max=0.6, step=0.05, value=-0.1,
                       marks={i / 10: str(i / 10) for i in range(-6, 7, 2)}),
            html.Label("Центр Z", style=SLIDER_STYLE),
            dcc.Slider(id='center-z-slider', min=-0.6, max=0.6, step=0.05, value=0.3,
                       marks={i / 10: str(i / 10) for i in range(-6, 7, 2)}),
            html.Label("Евклидов радиус", style=SLIDER_STYLE),
            dcc.Slider(id='radius-slider', min=0.05, max=0.8, step=0.05, value=0.4,
                       marks={i / 10: str(i / 10) for i in range(1, 9)}),
        ])
    ])
])

tab_orosphere = dcc.Tab(label='Орисфера', value='orosphere', children=[
    html.Div([
        html.Button('Скрыть/показать геодезические', id='toggle-guiding-lines-button',
                    n_clicks=0, style=BTN_STYLE),
        dcc.Store(id='guiding-lines-visibility-store', data={'visible': True}),
    ], style={'textAlign': 'center'}),
    html.Div(style=ROW_STYLE, children=[
        dcc.Graph(id='hyperbolic-orosphere-graph', style=GRAPH_STYLE),
        html.Div(style=PANEL_STYLE, children=[
            html.Label("Угол φ (полярный)", style={'marginTop': '0', 'display': 'block'}),
            dcc.Slider(id='phi-slider', min=0.05, max=np.pi - 0.05, step=0.05,
                       value=np.pi / 4, marks=PI_MARKS),
            html.Label("Угол θ (азимутальный)", style=SLIDER_STYLE),
            dcc.Slider(id='theta-slider', min=0, max=2 * np.pi, step=0.1,
                       value=np.pi / 4, marks=TAU_MARKS),
            html.Label("Радиус орисферы", style=SLIDER_STYLE),
            dcc.Slider(id='r-horo-slider', min=0.05, max=0.9, step=0.05, value=0.4,
                       marks={i / 10: str(i / 10) for i in range(1, 10, 2)}),
        ])
    ])
])

tab_equidistant = dcc.Tab(label='Эквидистанта', value='equidistant', children=[
    html.Div([
        html.Button('Скрыть/показать геод. плоскость', id='toggle-plane-button',
                    n_clicks=0, style=BTN_STYLE),
        dcc.Store(id='plane-visibility-store', data={'visible': True}),
    ], style={'textAlign': 'center'}),
    html.Div(style=ROW_STYLE, children=[
        dcc.Graph(id='hyperbolic-equidistant-graph', style=GRAPH_STYLE),
        html.Div(style=PANEL_STYLE, children=[
            html.Label("Угол φ нормали", style={'marginTop': '0', 'display': 'block'}),
            dcc.Slider(id='eq-phi-slider', min=0.05, max=np.pi - 0.05, step=0.05,
                       value=np.pi / 3, marks=PI_MARKS),
            html.Label("Угол θ нормали", style=SLIDER_STYLE),
            dcc.Slider(id='eq-theta-slider', min=0, max=2 * np.pi, step=0.1,
                       value=np.pi / 4, marks=TAU_MARKS),
            html.Label("Расстояние h", style=SLIDER_STYLE),
            dcc.Slider(id='eq-h-slider', min=0.1, max=2.5, step=0.1, value=0.6,
                       marks={v: str(v) for v in [0.5, 1.0, 1.5, 2.0, 2.5]}),
        ])
    ])
])

app.layout = html.Div(
    style={'fontFamily': 'Arial, sans-serif', 'fontSize': '12px', 'color': 'black'},
    children=[
        html.H1("Модель Бельтрами-Клейна", style={'textAlign': 'center', 'marginBottom': '0'}),
        dcc.Tabs(id='main-tabs', value='sphere',
                 children=[tab_sphere, tab_orosphere, tab_equidistant]),
    ]
)


# ==============================================================================
# CALLBACKS
# ==============================================================================

@app.callback(
    Output('hyperbolic-sphere-graph', 'figure'),
    Output('axes-visibility-store', 'data'),
    [Input('radius-slider', 'value'),
     Input('center-x-slider', 'value'),
     Input('center-y-slider', 'value'),
     Input('center-z-slider', 'value'),
     Input('toggle-axes-button', 'n_clicks')],
    State('axes-visibility-store', 'data')
)
def update_sphere(radius, cx, cy, cz, n_clicks, axes_data):
    ctx = dash.callback_context
    if ctx.triggered and ctx.triggered[0]['prop_id'].split('.')[0] == 'toggle-axes-button':
        axes_data = {'visible': not axes_data['visible']}
    return create_sphere_figure(radius, cx, cy, cz, show_axes=axes_data['visible']), axes_data


@app.callback(
    Output('hyperbolic-orosphere-graph', 'figure'),
    Output('guiding-lines-visibility-store', 'data'),
    [Input('phi-slider', 'value'),
     Input('theta-slider', 'value'),
     Input('r-horo-slider', 'value'),
     Input('toggle-guiding-lines-button', 'n_clicks')],
    State('guiding-lines-visibility-store', 'data')
)
def update_orosphere(phi, theta, r_horo, n_clicks, lines_data):
    ctx = dash.callback_context
    if ctx.triggered and ctx.triggered[0]['prop_id'].split('.')[0] == 'toggle-guiding-lines-button':
        lines_data = {'visible': not lines_data['visible']}
    return create_orosphere_figure(phi, theta, r_horo, show_guiding_lines=lines_data['visible']), lines_data


@app.callback(
    Output('hyperbolic-equidistant-graph', 'figure'),
    Output('plane-visibility-store', 'data'),
    [Input('eq-phi-slider', 'value'),
     Input('eq-theta-slider', 'value'),
     Input('eq-h-slider', 'value'),
     Input('toggle-plane-button', 'n_clicks')],
    State('plane-visibility-store', 'data')
)
def update_equidistant(phi, theta, h, n_clicks, plane_data):
    ctx = dash.callback_context
    if ctx.triggered and ctx.triggered[0]['prop_id'].split('.')[0] == 'toggle-plane-button':
        plane_data = {'visible': not plane_data['visible']}
    return create_equidistant_figure(phi, theta, h, show_plane=plane_data['visible']), plane_data


server = app.server
if __name__ == '__main__':
    app.run(debug=True)
