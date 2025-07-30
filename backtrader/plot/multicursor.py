from ..utils.py3 import zip

class Widget(object):
    """
    Abstract base class for GUI neutral widgets
    """
    drawon = True
    eventson = True
    _active = True

    def set_active(self, active):
        """Set whether the widget is active.
        """
        self._active = active

    def get_active(self):
        """Get whether the widget is active.
        """
        return self._active

    # set_active is overriden by SelectorWidgets.
    active = property(get_active, lambda self, active: self.set_active(active),
                      doc="Is the widget active?")

    def ignore(self, event):
        """Return True if event should be ignored.
        This method (or a version of it) should be called at the beginning
        of any event callback.
        """
        return not self.active


class MultiCursor(Widget):
    """
    Provide a vertical (default) and/or horizontal line cursor shared between
    multiple axes.

    For the cursor to remain responsive you much keep a reference to
    it.

    Example usage::

        from matplotlib.widgets import MultiCursor
        from pylab import figure, show, np

        t = np.arange(0.0, 2.0, 0.01)
        s1 = np.sin(2*np.pi*t)
        s2 = np.sin(4*np.pi*t)
        fig = figure()
        ax1 = fig.add_subplot(211)
        ax1.plot(t, s1)


        ax2 = fig.add_subplot(212, sharex=ax1)
        ax2.plot(t, s2)

        multi = MultiCursor(fig.canvas, (ax1, ax2), color='r', lw=1,
                            horizOn=False, vertOn=True)
        show()

    """
    def __init__(self, canvas, axes, useblit=True,
                 horizOn=False, vertOn=True,
                 horizMulti=False, vertMulti=True,
                 horizShared=True, vertShared=False,
                 **lineprops):

        self.canvas = canvas
        self.axes = axes
        self.horizOn = horizOn
        self.vertOn = vertOn
        self.horizMulti = horizMulti
        self.vertMulti = vertMulti

        self.visible = True
        self.useblit = useblit and self.canvas.supports_blit
        self.background = None
        self.needclear = False

        if self.useblit:
            lineprops['animated'] = True

        self.vlines = []
        if vertOn:
            xmin, xmax = axes[-1].get_xlim()
            xmid = 0.5 * (xmin + xmax)

            for ax in axes:
                if not horizShared:
                    xmin, xmax = ax.get_xlim()
                    xmid = 0.5 * (xmin + xmax)

                vline = ax.axvline(xmid, visible=False, **lineprops)
                self.vlines.append(vline)

        self.hlines = []
        if horizOn:
            ymin, ymax = axes[-1].get_ylim()
            ymid = 0.5 * (ymin + ymax)

            for ax in axes:
                if not vertShared:
                    ymin, ymax = ax.get_ylim()
                    ymid = 0.5 * (ymin + ymax)

                hline = ax.axhline(ymid, visible=False, **lineprops)
                self.hlines.append(hline)

        self.connect()

    def connect(self):
        """connect events"""
        self._cidmotion = self.canvas.mpl_connect('motion_notify_event',
                                                  self.onmove)
        self._ciddraw = self.canvas.mpl_connect('draw_event', self.clear)

    def disconnect(self):
        """disconnect events"""
        self.canvas.mpl_disconnect(self._cidmotion)
        self.canvas.mpl_disconnect(self._ciddraw)

    def clear(self, event):
        """clear the cursor"""
        if self.ignore(event):
            return
        if self.useblit:
            self.background = (
                self.canvas.copy_from_bbox(self.canvas.figure.bbox))
        for line in self.vlines + self.hlines:
            line.set_visible(False)

    def onmove(self, event):
        if self.ignore(event):
            return
        if event.inaxes is None:
            return
        if not self.canvas.widgetlock.available(self):
            return
        self.needclear = True
        if not self.visible:
            return
        if self.vertOn:
            for line in self.vlines:
                visible = self.visible
                if not self.vertMulti:
                    visible = visible and line.axes == event.inaxes

                if visible:
                    line.set_xdata((event.xdata, event.xdata))
                    line.set_visible(visible)
        if self.horizOn:
            for line in self.hlines:
                visible = self.visible
                if not self.horizMulti:
                    visible = visible and line.axes == event.inaxes
                if visible:
                    line.set_ydata((event.ydata, event.ydata))
                    line.set_visible(self.visible)
        self._update(event)

    def _update(self, event):
        if self.useblit:
            if self.background is not None:
                self.canvas.restore_region(self.background)
            if self.vertOn:
                for ax, line in zip(self.axes, self.vlines):
                    if self.vertMulti or event.inaxes == line.axes:
                        ax.draw_artist(line)

            if self.horizOn:
                for ax, line in zip(self.axes, self.hlines):
                    if self.horizMulti or event.inaxes == line.axes:
                        ax.draw_artist(line)
            self.canvas.blit(self.canvas.figure.bbox)
        else:
            self.canvas.draw_idle()

class MultiCursor2(Widget):
    """
    Provide a vertical (default) and/or horizontal line cursor shared between
    multiple axes.
    For the cursor to remain responsive you much keep a reference to
    it.
    Example usage::
        from matplotlib.widgets import MultiCursor
        from pylab import figure, show, np
        t = np.arange(0.0, 2.0, 0.01)
        s1 = np.sin(2*np.pi*t)
        s2 = np.sin(4*np.pi*t)
        fig = figure()
        ax1 = fig.add_subplot(211)
        ax1.plot(t, s1)
        ax2 = fig.add_subplot(212, sharex=ax1)
        ax2.plot(t, s2)
        multi = MultiCursor(fig.canvas, (ax1, ax2), color='r', lw=1,
                            horizOn=False, vertOn=True)
        show()
    """
    def __init__(self, canvas, axes, useblit=True, horizOn=False, vertOn=True,
                 **lineprops):

        self.canvas = canvas
        self.axes = axes
        self.horizOn = horizOn
        self.vertOn = vertOn

        xmin, xmax = axes[-1].get_xlim()
        xmid = 0.5 * (xmin + xmax)

        self.visible = True
        self.useblit = useblit and self.canvas.supports_blit
        self.background = None
        self.needclear = False

        if self.useblit:
            lineprops['animated'] = True

        if vertOn:
            self.vlines = [ax.axvline(xmid, visible=False, **lineprops)
                           for ax in axes]
        else:
            self.vlines = []

        if horizOn:
            self.hlines = []
            for ax in axes:
                ymin, ymax = ax.get_ylim()
                ymid = 0.5 * (ymin + ymax)
                hline = ax.axhline(ymid, visible=False, **lineprops)
                self.hlines.append(hline)
        else:
            self.hlines = []

        self.connect()

    def connect(self):
        """connect events"""
        self._cidmotion = self.canvas.mpl_connect('motion_notify_event',
                                                  self.onmove)
        self._ciddraw = self.canvas.mpl_connect('draw_event', self.clear)

    def disconnect(self):
        """disconnect events"""
        self.canvas.mpl_disconnect(self._cidmotion)
        self.canvas.mpl_disconnect(self._ciddraw)

    def clear(self, event):
        """clear the cursor"""
        if self.ignore(event):
            return
        if self.useblit:
            self.background = (
                self.canvas.copy_from_bbox(self.canvas.figure.bbox))
        for line in self.vlines + self.hlines:
            line.set_visible(False)

    def onmove(self, event):
        if self.ignore(event):
            return
        if event.inaxes is None:
            return

        if not self.canvas.widgetlock.available(self):
            return
        self.needclear = True
        if not self.visible:
            return
        if self.vertOn:
            for line in self.vlines:
                visible = True or line.axes == event.inaxes
                line.set_xdata((event.xdata, event.xdata))
                line.set_visible(visible)
        if self.horizOn:
            for line in self.hlines:
                visible = line.axes == event.inaxes
                line.set_ydata((event.ydata, event.ydata))
                line.set_visible(visible)
        self._update(event)

    def _update(self, event):
        if self.useblit:
            if self.background is not None:
                self.canvas.restore_region(self.background)
            if self.vertOn:
                for ax, line in zip(self.axes, self.vlines):
                    ax.draw_artist(line)
            if self.horizOn:
                for ax, line in zip(self.axes, self.hlines):
                    ax.draw_artist(line)
            self.canvas.blit(self.canvas.figure.bbox)
        else:
            self.canvas.draw_idle()
