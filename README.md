ttvsnap
=======

Ttvsnap is script that will periodically save Twitch.tv screenshots using Twitch API preview thumbnails.

Usage
=====

You will need Python 3.3+.

To start the script, run something similar to this:

        python3 ttvsnap.py verycoolstreamer ./screenshots/ --client-id YOUR_CLIENT_ID_HERE

(Replace `python3` as needed, `python.exe` for example.)

The script will check every ~5 minutes and save the screenshot to the given directory. For streams that run 24/7, you can use the `--subdir` option to create a directory for each day.

As a convenience, it supports generating thumbnails using ImageMagick. Ensure that the `convert` command exists and add the `--thubmnail` option.

For the list of options, use the `--help` option.

Tips
----

If you are using this script for a website of some sort, you may want to look into some daemon service management tools to restart it if it crashes. On Linux, look into creating Upstart or Systemd configuration files for it.

As of writing, Twitch caches preview images for 5 minutes so setting it to low values such as 1 minute may be useless. However, the script will use the `If-Modified-Since` HTTP header to avoid downloading images repeatedly.

Client ID is required after 2016-08-08. You can get a Client ID in the settings page by registering an application and using the Client ID for personal use.  
