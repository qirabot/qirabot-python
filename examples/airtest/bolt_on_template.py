"""Mix native Airtest Templates with qirabot AI in one script.

The whole point of bolting qirabot onto Airtest: keep the Airtest code that
already works (image Templates, swipes) and use AI only where Templates are
brittle — text that changes, elements that move across versions/OEMs, localized
labels. You migrate incrementally instead of rewriting your suite.

Run (connect a device first; the .png below is a placeholder for one of your own
Template images):
    export QIRA_API_KEY="qk_..."
    python examples/airtest/bolt_on_template.py
"""

import os

from airtest.core.api import G, Template, connect_device, start_app, stop_app, swipe, touch

from qirabot import Qirabot

APP = "com.example.myapp"  # <-- replace with your app's package / bundle id

connect_device(os.environ.get("AIRTEST_DEVICE", "Android:///"))
start_app(APP)                               # open the app
bot = Qirabot(task_name="airtest-mixed").bind(G)

try:
    # --- native Airtest: keep the stable image-based steps you already have ---
    touch(Template("tpl_home_button.png"))   # replace with your own template
    swipe((500, 1500), (500, 500))            # scroll up with a native swipe

    # --- qirabot AI: use it where Templates keep breaking ---
    bot.click("Settings menu item")           # AI-located, survives UI drift
    email = bot.extract("the account email shown on screen")
    print("email:", email)
    assert bot.verify("the account screen is open")
finally:
    stop_app(APP)                            # close the app
    bot.close()


# For reference, the same call without bind() — any of these targets work, and
# all resolve to the current Airtest device:
#
#   import airtest.core.api as air
#   bot = Qirabot()
#   bot.click(G, "Settings menu item")        # the G global
#   bot.click(air, "Settings menu item")      # the airtest.core.api module
#   dev = connect_device("Android:///")
#   bot.click(dev, "Settings menu item")      # an explicit device handle
