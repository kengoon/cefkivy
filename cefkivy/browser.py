# Import cef as first module! (it's important)
import ctypes
import sys
import os

libcef_so = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libcef.so')
if os.path.exists(libcef_so):
    # Import local module
    ctypes.CDLL(libcef_so, ctypes.RTLD_GLOBAL)
    if 0x02070000 <= sys.hexversion < 0x03000000:
        import cefpython_py27 as cefpython
    else:
        raise Exception("Unsupported python version: %s" % sys.version)
else:
    # Import from package
    from cefpython3 import cefpython


from kivy.app import App
from kivy.base import EventLoop
from kivy.graphics import Color, Rectangle
from kivy.graphics.texture import Texture
from kivy.properties import *
from kivy.uix.widget import Widget
from cefkeyboard import CefKeyboardManager
from kivy.clock import Clock
from kivy.core.window import Window


class CefBrowser(Widget):
    # Keyboard mode: "global" or "local".
    # 1. Global mode forwards keys to CEF all the time.
    # 2. Local mode forwards keys to CEF only when an editable
    #    control is focused (input type=text|password or textarea).
    keyboard_mode = OptionProperty("local", options=("global", "local"))
    url = StringProperty("about:blank")
    current_url = StringProperty("")
    resources_dir = StringProperty("")
    browser = None
    popup = None
    touches = []
    is_loading = BooleanProperty(True)

    _reset_js_bindings = False  # See set_js_bindings()
    _js_bindings = None  # See set_js_bindings()

    def __init__(self, *largs, **dargs):
        super(CefBrowser, self).__init__()
        self.url = dargs.get("url", "")
        self.keyboard_mode = dargs.get("keyboard_mode", "local")
        self.resources_dir = dargs.get("resources_dir", "")
        self.keyboard_above_classes = dargs.get("keyboard_above_classes", [])
        switches = dargs.get("switches", {})
        self.__rect = None
        self.browser = None
        self.popup = CefBrowserPopup(self)

        self.register_event_type("on_loading_state_change")
        self.register_event_type("on_address_change")
        self.register_event_type("on_title_change")
        self.register_event_type("on_before_popup")
        self.register_event_type("on_load_start")
        self.register_event_type("on_load_end")
        self.register_event_type("on_load_error")
        self.register_event_type("on_certificate_error")
        self.register_event_type("on_js_dialog")
        self.register_event_type("on_before_unload_dialog")

        self.key_manager = CefKeyboardManager(cefpython=cefpython, browser_widget=self)

        self.texture = Texture.create(size=self.size, colorfmt='rgba', bufferfmt='ubyte')
        self.texture.flip_vertical()
        with self.canvas:
            Color(1, 1, 1)
            self.__rect = Rectangle(pos=self.pos, size=self.size, texture=self.texture)

        md = cefpython.GetModuleDirectory()

        # Determine if default resources dir should be used or a custom
        if self.resources_dir:
            resources = self.resources_dir
        else:
            resources = md

        def cef_loop(*largs):
            cefpython.MessageLoopWork()
        Clock.schedule_interval(cef_loop, 0)

        settings = {
                    #"debug": True,
                    "log_severity": cefpython.LOGSEVERITY_INFO,
                    #"log_file": "debug.log",
                    "persist_session_cookies": True,
                    "release_dcheck_enabled": True,  # Enable only when debugging.
                    "locales_dir_path": os.path.join(md, "locales"),
                    "browser_subprocess_path": "%s/%s" % (cefpython.GetModuleDirectory(), "subprocess")
                }
        cefpython.Initialize(settings, switches)

        windowInfo = cefpython.WindowInfo()
        windowInfo.SetAsOffscreen(0)
        cefpython.SetGlobalClientCallback("OnCertificateError", self.OnCertificateError)
        self.browser = cefpython.CreateBrowserSync(windowInfo, {}, navigateUrl=self.url)

        # Set cookie manager
        cookie_manager = cefpython.CookieManager.GetGlobalManager()
        cookie_path = os.path.join(resources, "cookies")
        cookie_manager.SetStoragePath(cookie_path, True)

        self.browser.SendFocusEvent(True)
        ch = ClientHandler(self)
        self.browser.SetClientHandler(ch)
        self.set_js_bindings()
        self.browser.WasResized()
        self.bind(size=self.realign)
        self.bind(pos=self.realign)
        self.bind(keyboard_mode=self.set_keyboard_mode)
        if self.keyboard_mode == "global":
            self.request_keyboard()

    def set_js_bindings(self):
        # Needed to introduce set_js_bindings again because the freeze of sites at load took over.
        # As an example 'http://www.htmlbasix.com/popup.shtml' freezed every time. By setting the js
        # bindings again, the freeze rate is at about 35%. Check git to see how it was done, before using
        # this function ...
        # I (jegger) have to be honest, that I don't have a clue why this is acting like it does!
        # I hope simon (REN-840) can resolve this once in for all...
        #
        # ORIGINAL COMMENT:
        # When browser.Navigate() is called, some bug appears in CEF
        # that makes CefRenderProcessHandler::OnBrowserDestroyed()
        # is being called. This destroys the javascript bindings in
        # the Render process. We have to make the js bindings again,
        # after the call to Navigate() when OnLoadingStateChange()
        # is called with isLoading=False. Problem reported here:
        # http://www.magpcss.org/ceforum/viewtopic.php?f=6&t=11009
        if not self._js_bindings:
            self._js_bindings = cefpython.JavascriptBindings(bindToFrames=True, bindToPopups=True)
            self._js_bindings.SetFunction("__kivy__keyboard_update", self.keyboard_update)
        self.browser.SetJavascriptBindings(self._js_bindings)

    def realign(self, *largs):
        ts = self.texture.size
        ss = self.size
        schg = (ts[0] != ss[0] or ts[1] != ss[1])
        if schg:
            self.texture = Texture.create(size=self.size, colorfmt='rgba', bufferfmt='ubyte')
            self.texture.flip_vertical()
        if self.__rect:
            with self.canvas:
                Color(1, 1, 1)
                self.__rect.pos = self.pos
                if schg:
                    self.__rect.size = self.size
            if schg:
                self.update_rect()
        if self.browser:
            self.browser.WasResized()
            self.browser.NotifyScreenInfoChanged()
        # Bring keyboard to front
        try:
            k = self.__keyboard.widget
            p = k.parent
            p.remove_widget(k)
            p.add_widget(k)
        except:
            pass

    def update_rect(self):
        if self.__rect:
            self.__rect.texture = self.texture

    def on_url(self, instance, value):
        if self.browser and value:
            self.browser.Navigate(self.url)
            self._reset_js_bindings = True

    def set_keyboard_mode(self, *largs):
        if self.keyboard_mode == "global":
            self.request_keyboard()
        else:
            self.release_keyboard()

    def on_loading_state_change(self, isLoading, canGoBack, canGoForward):
        self.is_loading = isLoading

    def on_address_change(self, frame, url):
        self.current_url = url

    def on_title_change(self, newTitle):
        pass

    def on_before_popup(self, browser, frame, targetUrl, targetFrameName,
            popupFeatures, windowInfo, client, browserSettings, noJavascriptAccess):
        pass

    def on_js_dialog(self, browser, origin_url, accept_lang, dialog_type, message_text, default_prompt_text, callback,
                     suppress_message):
        pass

    def on_before_unload_dialog(self, browser, message_text, is_reload, callback):
        pass

    def on_certificate_error(self):
        pass

    def on_load_start(self, frame):
        pass

    def on_load_end(self, frame, httpStatusCode):
        pass

    def on_load_error(self, frame, errorCode, errorText, failedUrl):
        print("on_load_error=> Code: %s, errorText: %s, failedURL: %s" % (errorCode, errorText, failedUrl))

    def OnCertificateError(self, err, url, cb):
        print err, url, cb
        # Check if cert verification is disabled
        if os.path.isfile("/etc/rentouch/ssl-verification-disabled"):
            cb.Continue(True)
        else:
            cb.Continue(False)
            self.dispatch("on_certificate_error")

    __keyboard = None

    def keyboard_update(self, shown, rect, attributes):
        """
        :param shown: Show keyboard if true, hide if false (blur)
        :param rect: [x,y,width,height] of the input element
        :param attributes: Attributes of HTML element
        """
        if shown:
            above = (
                'class' in attributes
                and attributes['class'] in self.keyboard_above_classes
            )

            self.request_keyboard()
            kb = self.__keyboard.widget
            if len(rect) < 4:
                kb.pos = ((Window.width-kb.width*kb.scale)/2, 10)
            else:
                x = self.x+rect[0]+(rect[2]-kb.width*kb.scale)/2
                y = self.height+self.y-rect[1]-rect[3]-kb.height*kb.scale
                if above:
                    # If keyboard should displayed above the input field
                    # Above is good on e.g. search boxes with results displayed
                    # bellow the input field
                    y = self.height+self.y-rect[1]
                if y < 0:
                    # If keyboard is bellow the window height
                    rightx = self.x+rect[0]+rect[2]
                    spleft = self.x+rect[0]
                    spright = Window.width-rightx
                    y = 0
                    x = rightx if spleft <= spright else spleft-kb.width*kb.scale
                elif y+kb.height*kb.scale > Window.height:
                    # If keyboard is above the window height
                    rightx = self.x+rect[0]+rect[2]
                    spleft = self.x+rect[0]
                    spright = Window.width-rightx
                    y = Window.height-kb.height*kb.scale
                    x = rightx if spleft <= spright else spleft-kb.width*kb.scale
                elif x < 0:
                    x = 0
                elif Window.width < x+kb.width*kb.scale:
                    x = Window.width-kb.width*kb.scale
                kb.pos = (x, y)
        else:
            self.release_keyboard()

    def request_keyboard(self):
        if not self.__keyboard:
            self.__keyboard = EventLoop.window.request_keyboard(self.release_keyboard, self)
            self.__keyboard.bind(on_key_down=self.on_key_down)
            self.__keyboard.bind(on_key_up=self.on_key_up)
        self.key_manager.reset_all_modifiers()
        # Not sure if it is still required to send the focus
        # (some earlier bug), but it shouldn't hurt to call it.
        self.browser.SendFocusEvent(True)

    def release_keyboard(self, *kwargs):
        # When using local keyboard mode, do all the request
        # and releases of the keyboard through js bindings,
        # otherwise some focus problems arise.
        self.key_manager.reset_all_modifiers()
        if not self.__keyboard:
            return
        # If we blur the field on keyboard release, jumping between form
        # fields with tab won't work.
        # self.browser.GetFocusedFrame().ExecuteJavascript("__kivy__on_escape()")
        self.__keyboard.unbind(on_key_down=self.on_key_down)
        self.__keyboard.unbind(on_key_up=self.on_key_up)
        self.__keyboard.release()
        self.__keyboard = None

    def on_key_down(self, *largs):
        self.key_manager.kivy_on_key_down(self.browser, *largs)

    def on_key_up(self, *largs):
        self.key_manager.kivy_on_key_up(self.browser, *largs)

    def go_back(self):
        self.browser.GoBack()

    def go_forward(self):
        self.browser.GoForward()

    def delete_cookie(self, url=""):
        """ Deletes the cookie with the given url. If url is empty all cookies get deleted.
        """
        if cookie_manager := cefpython.CookieManager.GetGlobalManager():
            cookie_manager.DeleteCookies(url, "")
        else:
            print("No cookie manager found!, Can't delete cookie(s)")

    def on_touch_down(self, touch, *kwargs):
        if not self.collide_point(*touch.pos):
            return
        if self.keyboard_mode == "global":
            self.request_keyboard()
        else:
           Window.release_all_keyboards()

        touch.is_dragging = False
        touch.is_scrolling = False
        touch.is_right_click = False
        self.touches.append(touch)
        touch.grab(self)

        return True

    def on_touch_move(self, touch, *kwargs):
        if touch.grab_current is not self:
            return

        y = self.height-touch.pos[1] + self.pos[1]
        x = touch.x - self.pos[0]

        if len(self.touches) == 1:
            # Dragging
            if (abs(touch.dx) > 5 or abs(touch.dy) > 5) or touch.is_dragging:
                if touch.is_dragging:
                    self.browser.SendMouseMoveEvent(x, y, mouseLeave=False)
                else:
                    self.browser.SendMouseClickEvent(x, y, cefpython.MOUSEBUTTON_LEFT,
                                                     mouseUp=False, clickCount=1)
                    touch.is_dragging = True
        elif len(self.touches) == 2:
            # Scroll only if a given distance is passed once (could be right click)
            touch1, touch2 = self.touches[:2]
            dx = touch2.dx / 2. + touch1.dx / 2.
            dy = touch2.dy / 2. + touch1.dy / 2.
            if (abs(dx) > 5 or abs(dy) > 5) or touch.is_scrolling:
                # Scrolling
                touch.is_scrolling = True
                self.browser.SendMouseWheelEvent(touch.x, self.height-touch.pos[1], dx, -dy)
        return True

    def on_touch_up(self, touch, *kwargs):
        if touch.grab_current is not self:
            return

        y = self.height-touch.pos[1] + self.pos[1]
        x = touch.x - self.pos[0]

        if len(self.touches) == 2:
            if not touch.is_scrolling:
                # Right click (mouse down, mouse up)
                self.touches[0].is_right_click = self.touches[1].is_right_click = True
                self.browser.SendMouseClickEvent(x, y, cefpython.MOUSEBUTTON_RIGHT,
                                                 mouseUp=False, clickCount=1
                                                 )
                self.browser.SendMouseClickEvent(x, y, cefpython.MOUSEBUTTON_RIGHT,
                                                 mouseUp=True, clickCount=1
                                                 )
        elif touch.is_dragging:
            # Drag end (mouse up)
            self.browser.SendMouseClickEvent(
                x,
                y,
                cefpython.MOUSEBUTTON_LEFT,
                mouseUp=True, clickCount=1
            )
        elif not touch.is_right_click:
            count = 2 if touch.is_double_tap else 1
            self.browser.SendMouseClickEvent(
                x,
                y,
                cefpython.MOUSEBUTTON_LEFT,
                mouseUp=False, clickCount=count
            )
            self.browser.SendMouseClickEvent(
                x,
                y,
                cefpython.MOUSEBUTTON_LEFT,
                mouseUp=True, clickCount=count
            )

        self.touches.remove(touch)
        touch.ungrab(self)
        return True


class CefBrowserPopup(Widget):
    rx = NumericProperty(0)
    ry = NumericProperty(0)
    rpos = ReferenceListProperty(rx, ry)

    def __init__ (self, parent, *largs, **dargs):
        super(CefBrowserPopup, self).__init__()
        self.browser_widget = parent
        self.__rect = None
        self.texture = Texture.create(size=self.size, colorfmt='rgba', bufferfmt='ubyte')
        self.texture.flip_vertical()
        with self.canvas:
            Color(1, 1, 1)
            self.__rect = Rectangle(pos=self.pos, size=self.size, texture=self.texture)
        self.bind(rpos=self.realign)
        self.bind(size=self.realign)
        parent.bind(pos=self.realign)
        parent.bind(size=self.realign)

    def realign(self, *largs):
        self.x = self.rx+self.browser_widget.x
        self.y = self.browser_widget.height-self.ry-self.height+self.browser_widget.y
        ts = self.texture.size
        ss = self.size
        schg = (ts[0] != ss[0] or ts[1] != ss[1])
        if schg:
            self.texture = Texture.create(size=self.size, colorfmt='rgba', bufferfmt='ubyte')
            self.texture.flip_vertical()
        if self.__rect:
            with self.canvas:
                Color(1, 1, 1)
                self.__rect.pos = self.pos
                if schg:
                    self.__rect.size = self.size
            if schg:
                self.update_rect()

    def update_rect(self):
        if self.__rect:
            self.__rect.texture = self.texture


class ClientHandler():
    def __init__(self, browserWidget):
        self.browser_widget = browserWidget

    # DisplayHandler

    def OnLoadingStateChange(self, browser, isLoading, canGoBack, canGoForward):
        self.browser_widget.dispatch("on_loading_state_change", isLoading, canGoBack, canGoForward)
        bw = self.browser_widget
        if bw._reset_js_bindings and not isLoading and bw:
            bw.set_js_bindings()
        if isLoading and bw \
                and bw.keyboard_mode == "local":
            # Release keyboard when navigating to a new page.
            bw.release_keyboard()

    def OnAddressChange(self, browser, frame, url):
        self.browser_widget.dispatch("on_address_change", frame, url)

    def OnTitleChange(self, browser, newTitle):
        self.browser_widget.dispatch("on_title_change", newTitle)

    def OnTooltip(self, *largs):
        return True

    def OnStatusMessage(self, *largs):
        pass

    def OnConsoleMessage(self, *largs):
        pass

    # DownloadHandler

    # DragHandler

    # JavascriptContextHandler
    def OnJSDialog(self, *kwargs):
        self.browser_widget.dispatch("on_js_dialog", *kwargs)
        return True

    def OnBeforeUnloadDialog(self, *kwargs):
        self.browser_widget.dispatch("on_before_unload_dialog", *kwargs)
        return True

    # KeyboardHandler

    def OnPreKeyEvent(self, *largs):
        pass

    def OnKeyEvent(self, *largs):
        pass

    # LifeSpanHandler

    def OnBeforePopup(self, *kwargs):
        self.browser_widget.dispatch("on_before_popup", *kwargs)
        return True

    # LoadHandler

    def OnLoadStart(self, browser, frame):
        self.browser_widget.dispatch("on_load_start", frame)
        bw = self.browser_widget
        if bw and bw.keyboard_mode == "local":
            lrectconstruct = "var rect = e.target.getBoundingClientRect();var lrect = [rect.left, rect.top, rect.width, rect.height];"
            if frame.GetParent():
                lrectconstruct = "var lrect = [];"
            jsCode = """
window.print=function(){console.log("Print dialog blocked")}
function isKeyboardElement(elem) {
    var tag = elem.tagName.toUpperCase();
    if (tag=="INPUT") return (["TEXT", "PASSWORD", "DATE", "DATETIME", "DATETIME-LOCAL", "EMAIL", "MONTH", "NUMBER", "SEARCH", "TEL", "TIME", "URL", "WEEK"].indexOf(elem.type.toUpperCase())!=-1);
    else if (tag=="TEXTAREA") return true;
    else {
        var tmp = elem;
        while (tmp && tmp.contentEditable=="inherit") {
            tmp = tmp.parentElement;
        }
        if (tmp && tmp.contentEditable) return true;
    }
    return false;
}

function getAttributes(elem){
    var attributes = {}
    for (var att, i = 0, atts = elem.attributes, n = atts.length; i < n; i++){
        att = atts[i];
        attributes[att.nodeName] = att.nodeValue
    }
    return attributes
}

window.addEventListener("focus", function (e) {
    """+lrectconstruct+"""
    attributes = getAttributes(e.target)
    if (isKeyboardElement(e.target)) __kivy__keyboard_update(true, lrect, attributes);
}, true);

window.addEventListener("blur", function (e) {
    """+lrectconstruct+"""
    attributes = getAttributes(e.target)
    __kivy__keyboard_update(false, lrect, attributes);
}, true);

function __kivy__on_escape() {
    if (document.activeElement) {
        document.activeElement.blur();
    }
}
            """
            frame.ExecuteJavascript(jsCode)

    def OnLoadEnd(self, browser, frame, httpStatusCode):
        self.browser_widget.dispatch("on_load_end", frame, httpStatusCode)
        #largs[0].SetZoomLevel(2.0) # this works at this point

    def OnLoadError(self, browser, frame, errorCode, errorText, failedUrl):
        self.browser_widget.dispatch("on_load_error", frame, errorCode, errorText, failedUrl)

    def OnRendererProcessTerminated(self, *largs):
        pass

    # RenderHandler

    def GetRootScreenRect(self, *largs):
        pass

    def GetViewRect(self, browser, rect):
        width, height = self.browser_widget.texture.size
        rect.append(0)
        rect.append(0)
        rect.append(width)
        rect.append(height)
        return True

    def GetScreenPoint(self, *largs):
        pass

    def GetScreenInfo(self, *largs):
        pass

    def OnPopupShow(self, browser, shown):
        self.browser_widget.remove_widget(self.browser_widget.popup)
        if shown:
            self.browser_widget.add_widget(self.browser_widget.popup)

    def OnPopupSize(self, browser, rect):
        self.browser_widget.popup.rpos = (rect[0], rect[1])
        self.browser_widget.popup.size = (rect[2], rect[3])

    def OnPaint(self, browser, paintElementType, dirtyRects, buf, width, height):
        b = buf.GetString(mode="bgra", origin="top-left")
        bw = self.browser_widget
        if paintElementType != cefpython.PET_VIEW:
            if bw.popup.texture.width*bw.popup.texture.height*4!=len(b):
                return True  # prevent segfault
            bw.popup.texture.blit_buffer(b, colorfmt='bgra', bufferfmt='ubyte')
            bw.popup.update_rect()
            return True
        if bw.texture.width*bw.texture.height*4!=len(b):
            return True  # prevent segfault
        bw.texture.blit_buffer(b, colorfmt='bgra', bufferfmt='ubyte')
        bw.update_rect()
        return True

    def OnCursorChange(self, *largs):
        pass

    def OnScrollOffsetChanged(self, *largs):
        pass

    # RequestHandler

    def OnBeforeBrowse(self, *largs):
        pass

    def OnBeforeResourceLoad(self, *largs):
        pass

    def GetResourceHandler(self, *largs):
        pass

    def OnResourceRedirect(self, *largs):
        pass

    def GetAuthCredentials(self, *largs):
        pass

    def OnQuotaRequest(self, *largs):
        pass

    def GetCookieManager(self, browser, mainUrl):
        if cookie_manager := cefpython.CookieManager.GetGlobalManager():
            return cookie_manager
        else:
            print("No cookie manager found!")

    def OnProtocolExecution(self, *largs):
        pass

    # RessourceHandler


if __name__ == '__main__':
    class CefApp(App):
        def build(self):
            cb = CefBrowser(url="http://jegger.ch/datapool/app/test1.html",
                            keyboard_above_classes=["select2-input", ])
            w = Widget()
            w.add_widget(cb)
            #cb.pos = (100, 10)
            #cb.size = (1720, 480)
            return cb

    CefApp().run()

    cefpython.Shutdown()

