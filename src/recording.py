# recording.py
#
# Copyright 2020 Alexey Mikhailov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from locale import gettext as _
import signal
import os
import datetime
import gi
from .recapp_constants import recapp_constants as constants
from subprocess import PIPE, Popen

gi.require_version('Gtk', '3.0')
gi.require_version('Gst', '1.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gio, GLib, Gst


class Recording:
    encoders = ["vp8enc", "x264enc"]
    formats = []

    def __init__(self, window):
        self.win = window
        self.settings = self.win.settings
        self.cpus = os.cpu_count() - 1
        self.coordinate_area = ""
        self.width_area = 0
        self.height_area = 0
        self.coordinate_mode = False
        self.is_recording = False
        self.is_cancelled = False
        self.is_timer_running = False
        self.is_recording_with_delay = False
        self.sound_record = self.settings.get_boolean('sound-on-computer')

        # Initialize recording timer
        GLib.timeout_add(1000, self.refresh_time)
        self.elapsed_time = datetime.timedelta()
        self.win._time_recording_label.set_label(str(self.elapsed_time).replace(":", "∶"))

        display_server = GLib.getenv('XDG_SESSION_TYPE').lower()
        self.is_wayland = True if display_server == "wayland" else False
        if self.is_wayland:
            self.GNOMEScreencast, self.GNOMESelectArea = self.get_gnome_screencast()

        self.output_format = self.get_output_format()
        self.output_quality = self.get_output_quality_string()

        self.video_str = "gst-launch-1.0 --eos-on-shutdown ximagesrc use-damage=1 show-pointer={0} ! video/x-raw," \
                         "framerate={1}/1 ! queue ! videoscale ! videoconvert ! {2} ! queue ! {3} name=mux ! " \
                         "queue ! filesink location='{4}'{5} "

    def start_recording(self, *args):
        if self.win.isFullscreenMode:
            self.record()
        elif self.win.isWindowMode:
            print('window mode')
        else:
            if self.is_wayland:
                self.on__select_area_wayland()  # was self
            else:
                self.on__select_area()  # was self
            self.record()

    def refresh_time(self):
        if self.is_timer_running:
            self.elapsed_time += datetime.timedelta(seconds=1)
            self.win._time_recording_label.set_label(str(self.elapsed_time).replace(":", "∶"))
        return True

    def record(self):
        if self.win.delayBeforeRecording > 0:
            self.win._main_stack.set_visible_child(self.win._delay_box)
            self.win._record_stop_record_button_stack.set_visible_child(self.win._cancel_button)
            self.win._menu_stack_revealer.set_reveal_child(False)
            self.is_recording_with_delay = True
            self.delay()
        else:
            self.record_logic()

    def get_gnome_screencast(self):
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return (Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None,
            "org.gnome.Shell.Screencast",
            "/org/gnome/Shell/Screencast",
            "org.gnome.Shell.Screencast", None
        ),
        Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None,
            "org.gnome.Shell.Screenshot",
            "/org/gnome/Shell/Screenshot",
            "org.gnome.Shell.Screenshot", None
        ))

    def on__select_area_wayland(self):
        self.wayland_coordinates = self.GNOMESelectArea.call_sync("SelectArea", None, Gio.DBusProxyFlags.NONE, -1, None)
        self.coordinate_mode = True

    def on__select_area(self):
        coordinate = Popen("slop -n -c 0.3,0.4,0.6,0.4 -l -t 0 -f '%w %h %x %y'", shell=True,
                           stdout=PIPE).communicate()
        listCoor = [int(i) for i in coordinate[0].decode().split()]
        if not listCoor[0] or not listCoor[1]:
            notification = Gio.Notification.new(constants["APPNAME"])
            notification.set_body(_("Please re-select the area"))
            self.win.application.send_notification(None, notification)
            return

        startx, starty, endx, endy = listCoor[2], listCoor[3], listCoor[2] + listCoor[0] - 1, listCoor[
            1] + listCoor[3] - 1
        if listCoor[0] % 2 == 0 and listCoor[1] % 2 == 0:
            self.width_area = endx - startx + 1
            self.height_area = endy - starty + 1
        elif listCoor[0] % 2 == 0 and listCoor[1] % 2 == 1:
            self.width_area = endx - startx + 1
            self.height_area = endy - starty + 2
        elif listCoor[0] % 2 == 1 and listCoor[1] % 2 == 1:
            self.width_area = endx - startx
            self.height_area = endy - starty
        elif listCoor[0] % 2 == 1 and listCoor[1] % 2 == 0:
            self.width_area = endx - startx + 2
            self.height_area = endy - starty + 1

        self.coordinate_area = f"startx={startx} starty={starty} endx={endx} endy={endy}"
        self.coordinate_mode = True

    def delay(self):
        self.win.time_delay = (self.win.delayBeforeRecording * 100)

        def countdown():
            if self.win.time_delay > 0:
                self.win.time_delay -= 10
                GLib.timeout_add(100, countdown)
                self.win._delay_label.set_label(str((self.win.time_delay // 100) + 1))
            else:
                self.is_recording_with_delay = False
                self.win._menu_stack_revealer.set_reveal_child(True)
                self.record_logic()
                self.win.time_delay = (self.win.delayBeforeRecording * 100)

        countdown()

    def record_logic(self):
        if self.is_cancelled:
            self.win.to_default()
            self.is_cancelled = False
        else:
            self.win._record_stop_record_button_stack.set_visible_child(self.win._stop_record_button)
            self.win._main_stack.set_visible_child(self.win._paused_start_stack_box)
            self.win._menu_stack.set_visible_child(self.win._pause_record_button)
            self.win.label_context = self.win._time_recording_label.get_style_context()
            self.win.label_context.add_class("recording")

            self.videoFrames = self.on__frames_changed()

            output_sound_string = self.get_sound_string()
            filename_time = _(constants["APPNAME"]) + "-" + datetime.datetime.now().strftime("%Y-%m-%d-%H:%M:%S")
            output_folder = self.win.settings.get_string('path-to-save-video-folder')
            filename = os.path.join(output_folder, filename_time)

            if self.output_format == "webm":
                mux = "webmmux"
                extension = ".webm"

            elif self.output_format == "mkv":
                mux = "matroskamux"
                extension = ".mkv"

            elif self.output_format == "mp4":
                mux = "mp4mux"
                extension = ".mp4"

            if self.is_wayland:
                RecorderPipeline = "{0} ! queue ! {1}".format(self.output_quality, mux)
                if self.coordinate_mode:
                    self.GNOMEScreencast.call_sync(
                        "ScreencastArea",
                        GLib.Variant.new_tuple(
                            GLib.Variant("i", self.wayland_coordinates[0]),
                            GLib.Variant("i", self.wayland_coordinates[1]),
                            GLib.Variant("i", self.wayland_coordinates[2]),
                            GLib.Variant("i", self.wayland_coordinates[3]),
                            GLib.Variant.new_string(filename + extension),
                            GLib.Variant("a{sv}",
                                         {"framerate": GLib.Variant("i", int(self.videoFrames)),
                                          "draw-cursor": GLib.Variant("b", self.win.recordMouse),
                                          "pipeline": GLib.Variant("s", RecorderPipeline)}
                                         ),
                        ),
                        Gio.DBusProxyFlags.NONE,
                        -1,
                        None)
                    self.coordinate_mode = False
                else:
                    self.GNOMEScreencast.call_sync(
                        "Screencast",
                        GLib.Variant.new_tuple(
                            GLib.Variant.new_string(filename + extension),
                            GLib.Variant("a{sv}",
                                         {"framerate": GLib.Variant("i", int(self.videoFrames)),
                                          "draw-cursor": GLib.Variant("b", self.win.recordMouse),
                                          "pipeline": GLib.Variant("s", RecorderPipeline)}
                                         ),
                        ),
                        Gio.DBusProxyFlags.NONE,
                        -1,
                        None)
            else:
                if self.coordinate_mode:
                    video_str = "gst-launch-1.0 --eos-on-shutdown ximagesrc show-pointer={0} " + self.coordinate_area + \
                                "! videoscale ! video/x-raw,width={1},height={2},framerate={3}/1 ! queue ! videoscale " \
                                "! videoconvert ! {4} ! queue ! {5} name=mux ! queue ! filesink location='{6}'{7} "
                    if self.sound_record:
                        self.video = Popen(
                            video_str.format(self.win.recordMouse, self.width_area, self.height_area,
                                             self.videoFrames, self.output_quality, mux, filename,
                                             extension) + output_sound_string, shell=True)

                    else:
                        self.video = Popen(
                            video_str.format(self.win.recordMouse, self.width_area, self.height_area,
                                             self.videoFrames, self.output_quality, mux, filename,
                                             extension), shell=True)

                    self.coordinate_mode = False
                else:
                    if self.sound_record:
                        self.video = Popen(
                            self.video_str.format(self.win.recordMouse, self.videoFrames, self.output_quality,
                                                      mux, filename, extension) + output_sound_string,
                            shell=True)
                    else:
                        self.video = Popen(
                            self.video_str.format(self.win.recordMouse, self.videoFrames, self.output_quality,
                                                  mux, filename, extension), shell=True)

            self.is_recording = True
            self.is_timer_running = True
            self.playsound('/com/github/amikha1lov/RecApp/sounds/chime.ogg')

    def get_output_quality_string(self):
        quality = self.settings.get_boolean("high-video-quality")
        if quality:  # high quality
            min_quantizer = 25
            max_quantizer = 25
            qp_min = 17
            qp_max = 17
        else:
            min_quantizer = 5
            max_quantizer = 10
            qp_min = 5
            qp_max = 5

        if self.output_format == "webm" or self.output_format == "mkv":
            quality_video = f"vp8enc min_quantizer={min_quantizer} max_quantizer={max_quantizer} cpu-used={self.cpus} cq_level=13 " \
                            f"deadline=1000000 threads={self.cpus}"
        elif self.output_format == "mp4":
            quality_video = f"x264enc qp-min={qp_min} qp-max={qp_max} speed-preset=1 threads={self.cpus} ! h264parse ! " \
                            "video/x-h264, profile=baseline"

        return quality_video

    def get_output_format(self):
        f_format = self.settings.get_enum("video-format")
        if f_format == 0:
            output_format = "webm"
        elif f_format == 1:
            output_format = "mkv"
        elif f_format == 2:
            output_format = "mp4"
        return output_format

    def on__frames_changed(self):
        frames = self.win.settings.get_enum("frames-per-second")
        if frames == 0:
            self.videoFrames = 15
        if frames == 1:
            self.videoFrames = 30
        if frames == 2:
            self.videoFrames = 60
        return self.videoFrames

    def get_sound_string(self):
        import pulsectl
        with pulsectl.Pulse() as pulse:
            sound_source = pulse.sink_list()[0].name
            if self.output_format == "webm" or self.output_format == "mkv":
                sound_output_string = "pulsesrc provide-clock=false device='{}.monitor' buffer-time=20000000 ! " \
                               "'audio/x-raw,depth=24,channels=2,rate=44100,format=F32LE,payload=96' ! queue ! " \
                               "audioconvert ! vorbisenc ! queue ! mux.".format(sound_source)

            elif self.output_format == "mp4":
                sound_output_string = "pulsesrc buffer-time=20000000 device='{}.monitor' ! 'audio/x-raw,channels=2," \
                               "rate=48000' ! queue ! audioconvert ! queue ! opusenc bitrate=512000 ! queue ! " \
                               "mux.".format(sound_source)
        return sound_output_string

    def stop_recording(self):
        if self.is_wayland:
            self.GNOMEScreencast.call_sync("StopScreencast", None, Gio.DBusCallFlags.NONE, -1, None)
        else:
            self.video.send_signal(signal.SIGINT)

        notification = Gio.Notification.new(constants["APPNAME"])
        notification.set_body(_("Recording is complete!"))
        notification.add_button(_("Open Folder"), "app.open-folder")
        notification.add_button(_("Open File"), "app.open-file")
        notification.set_default_action("app.open-file")
        self.win.application.send_notification(None, notification)

        self.is_recording = False
        self.is_timer_running = False

        self.win._record_stop_record_button_stack.set_visible_child(self.win._record_button)
        self.win._paused_start_stack.set_visible_child(self.win._recording_label)
        self.win._main_stack.set_visible_child(self.win._main_screen_box)
        self.win._menu_stack.set_visible_child(self.win._menu_button)
        self.win.label_context.remove_class("recording")

        self.elapsed_time = datetime.timedelta()
        self.win._time_recording_label.set_label(str(self.elapsed_time).replace(":", "∶"))

    def quit_app(self):
        if self.is_recording:
            self.stop_recording()
        self.win.destroy()

    def cancel_delay(self):
        self.win.time_delay = 0
        self.is_cancelled = True

    def playsound(self, sound):
        playbin = Gst.ElementFactory.make('playbin', 'playbin')
        playbin.props.uri = 'resource://' + sound
        set_result = playbin.set_state(Gst.State.PLAYING)
        bus = playbin.get_bus()
        bus.poll(Gst.MessageType.EOS, Gst.CLOCK_TIME_NONE)
        playbin.set_state(Gst.State.NULL)

    def find_encoders(self):
        for encoder in self.encoders:
            plugin = Gst.ElementFactory.find(encoder)
            if plugin:
                if encoder == "vp8enc":
                    self.formats.append("webm")
                    self.formats.append("mkv")
                elif encoder == "x264enc":
                    self.formats.append("mp4")
            else:
                print('Cannot find Gst plugin')
