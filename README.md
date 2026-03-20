# Summary
Use this package with your UseThatApp WebApps to acquire user license info from UseThatApp.com.

# Usage

## Single Page Dash App
In a simple single page Dash-Plotly application.

```python
from dash import Dash, dcc, html, Input, Output, ClientsideFunction
from usethatapp.webapps import get_product


app = Dash(__name__, external_scripts=[
    "https://cdn.jsdelivr.net/gh/UseThatApp/cdn@latest/usethatapp.js"
])

app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    html.Div(id='content'),
    dcc.Store(id='access-level-store', data=None, storage_type='memory'),
])

app.clientside_callback(
    ClientsideFunction(namespace='clientside', function_name='requestAccessLevel'),
    Output("access-level-store", "data"),
    Input('url', 'pathname')
)

@app.callback(
    Output('content', 'children'), 
    Input("access-level-store", "data")
)
def display_content_based_on_access(data):
    try:
        product = get_product(
            data['message'],
            public_key_path=r'/Path/To/File/Containing/UseThatApp_Public_Key',
            private_key_path=r'/Path/To/File/Containing/My_UTA_Private_Key'
        )
        # display content based on licensed plan
        if product == 'Pro':
            return html.Div([html.H1(["Paid Content"])])
    except Exception as e:
        # If there's an error (e.g. clientside hasn't populated the store yet), fall back to free content
        app.logger.exception("Error determining product: %s", e)
    return html.Div([html.H1(["Free Content"])])
```

## Mult-Page Dash App
In a multi-page Dash-Plotly application (using Dash Pages). The pattern below mirrors the single-page example: the main `app` registers a clientside callback that places the UseThatApp message into a `dcc.Store`, and each page reads that store (via a callback) and calls `get_product` to decide what to render.

### app.py
```python
import dash
from dash import Dash, html, dcc, Input, Output, ClientsideFunction

APP_TITLE = "Dash App"

app = Dash(
    __name__,
    title=APP_TITLE,
    use_pages=True,  # Allows us to register pages
    external_scripts=["https://cdn.jsdelivr.net/gh/UseThatApp/cdn@latest/usethatapp.js"],
)

# Top-level layout includes Location, a Store for the access payload, and the page container
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    dcc.Store(id='access-level-store', data=None, storage_type='memory'),
    dash.page_container,
])

# Register the same clientside callback used in the single-page example to populate the store
app.clientside_callback(
    ClientsideFunction(namespace='clientside', function_name='requestAccessLevel'),
    Output('access-level-store', 'data'),
    Input('url', 'pathname')
)

server = app.server

if __name__ == '__main__':
    app.run_server(debug=True)
```

### pages/home.py
```python
from dash import html, register_page, Input, Output, dash
from usethatapp.webapps import get_product

register_page(
    __name__,
    name='Home',
    path='/'
)

# Page layout is a placeholder container which we'll populate via a callback that
# listens to the shared `access-level-store` placed by the clientside JS.
def layout(**url_vars):
    return html.Div(id='home-content')

# Use dash.callback (so the callback is registered on the global app when pages are loaded)
@dash.callback(Output('home-content', 'children'), Input('access-level-store', 'data'))
def display_content_based_on_access(data):
    # Use the helper function to parse the message and determine the licensed product
    try:
        product = get_product(
            data['message'],
            public_key_path=r'/Path/To/File/Containing/UseThatApp_Public_Key',
            private_key_path=r'/Path/To/File/Containing/My_UTA_Private_Key'
        )

        if product == 'Pro':
            return html.Div([html.H1(["Paid Content"])])
    except Exception as e:
        # If there's an error (e.g. clientside hasn't populated the store yet), fall back to free content
        dash.get_app().server.logger.exception("Error determining product: %s", e)
    return html.Div([html.H1(["Free Content"])])
```

# Change Log

## Version 0.1.0 (03/19/2026)
- Initial release 

