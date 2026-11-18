"""The Files app (app.toml): a folder's files, any of them opened -- a text file edited live, with the actors; an image,
a PDF, a sound, a video shown -- all of it app_kit.fileedit's (FileEdit: its panel's requests, its mode, its agents'
file tools files_read, _edit, _write, _open, and the guard on their own edit tools).

    files.mode      {mode, by}: its mode (live until one is set)

It takes over the Editor's instances (the app it was, before it and the LaTeX editor were made of it: `replaces`) that
the LaTeX editor does not want (a folder with no LaTeX source at its top: `takes_over`)."""

from app_kit.fileedit import FileEdit


class FilesApp(FileEdit):
    CALLED = "Files app"
