# Prepper Box

An offline knowledge server for a small PC: Wikipedia and a shelf of practical books, a street map
with driving directions, courses, a ham-radio pack, a small AI you can ask questions, and a
notice board. Everything runs on the box. Once the content is downloaded it needs no internet;
phones and laptops reach it over your home network or the box's own Wi-Fi.

How-to page: <https://prepper-box.netlify.app>

| Page | What it is |
| --- | --- |
| `http://<box>/` | Start page with a card for each part |
| Library (`:8080`) | [Kiwix](https://kiwix.org): Wikipedia, WikiMed, iFixit, Wikivoyage, water/food/first-aid manuals, Stack Exchange Q&A (DIY, cooking, gardening, car repair, ham radio ...), Project Gutenberg, Khan Academy, Crash Course, TED-Ed |
| Map (`/maps/`) | World at city level, full street detail for the US (or any area you pick), address search, driving directions |
| Ask the Library (`:8090`) | Ask in plain English; it searches the library and a small AI answers from what it found, with links |
| Courses (`:8070`) | [Kolibri](https://learningequality.org/kolibri/): Khan math and science with exercises, CK-12, OpenStax, PhET ... |
| Ham Radio Pack | Band privileges, calling frequencies, FRS/GMRS/MURS/CB/marine channels, NOAA weather radio near you, net procedure, FCC Part 97 |
| Notice Board (`/board/`) | Notes and file sharing for everyone connected |
| Chat (`:3000`) | [Open WebUI](https://openwebui.com) on [Ollama](https://ollama.com), a 3B model on the CPU |

## What you need

- A 64-bit (x86-64) PC: 8 GB RAM, 4 threads. We use a 2013 Intel NUC (i5-4250U). No GPU needed.
- Disk: 1 TB holds everything below with room to spare. 250 GB still holds the essentials, a
  smaller Wikipedia and a regional map; the download script sizes itself to the free space.
- A USB stick (4 GB+) to install Ubuntu, and a wired network connection with internet for setup.
- Optional: a USB Wi-Fi adapter that supports AP mode (for the box's own Wi-Fi network), and a USB
  hard drive for a nightly backup.

## 1. Install Ubuntu Server

⚠️ This erases the PC's disk.

1. Download [Ubuntu Server](https://ubuntu.com/download/server) (24.04 LTS or newer) and write it
   to the USB stick with [balenaEtcher](https://etcher.balena.io) or [Rufus](https://rufus.ie).
2. Plug a keyboard, screen and network cable into the PC, boot from the stick (the boot-menu key is
   usually F10, F12 or Esc), and take the defaults, except:
   - **Your name / server name / username:** server name `prepper` (then it's `http://prepper.local`).
   - **SSH:** tick *Install OpenSSH server* so you can do the rest from another computer.
   - Skip the optional "featured snaps".
3. Reboot, remove the stick, log in, and note the address: `hostname -I`.

No keyboard and screen? A KVM-over-IP (PiKVM, TinyPilot, JetKVM ...) can boot the Ubuntu ISO as
virtual media and show the installer, so the same steps work remotely. There is also a hands-off
installer in [`extras/unattended-iso`](extras/unattended-iso/build-iso.sh); read its warnings first.

## 2. Set it up

From another computer: `ssh <you>@prepper.local` (or the address), then:

```sh
git clone https://github.com/builtatthedesk/prepper-box.git
cd prepper-box
sudo ./setup.sh
```

About 15 minutes. It installs Docker, copies `stack/` to `/opt/prepper`, starts every service,
downloads the AI model and prints the address of the start page. Content goes in `/srv/prepper`;
to use a different disk, mount it first and run `sudo DATA=/mnt/big ./setup.sh`.

## 3. Fill it

Each of these downloads in the background and can be re-run if it stops. Run them inside `tmux`
(`tmux new -s fill`) so they keep going after you disconnect. The library and map appear on the
start page as their files land.

| Step | Command | Size, time |
| --- | --- | --- |
| Library | `DATA=/srv/prepper /opt/prepper/get-content.sh` | Essentials 15 GB first, then the biggest Wikipedia that fits (119 GB with pictures), then extras if there's room. A day or two. |
| Map | `DATA=/srv/prepper /opt/prepper/get-maps.sh` | 19 GB for the US. Smaller area: `BBOX=minlon,minlat,maxlon,maxlat` |
| Address search | `DATA=/srv/prepper /opt/prepper/get-geocoder.sh` | 11 GB download, 30 GB unpacked, US only |
| Courses | `/opt/prepper/kolibri/import-channels.sh` | ~110 GB of channels; edit the list to pick |
| Manuals shelf | `python3 /opt/prepper/shelf/build.py /srv/prepper/shelf /srv/prepper/zim` | Public-domain manuals from `shelf/manifest.tsv`, OCR'd into a searchable book |
| Ham pack | `HOME_LOC="39.83,-98.58,Lebanon KS" CALL=N0CALL python3 /opt/prepper/ham/build.py /srv/prepper/ham /srv/prepper/zim` | Small; weather transmitters near HOME_LOC |
| Directions | `stack/get-routing.sh` on a bigger computer, then copy over | Needs 16 GB RAM to build; see the comments in the script. `STATES="ohio indiana"` picks the area (default: Rhode Island, as a quick test) |
| Satellite / topo | `python3 stack/get-satellite.py ...` then `pmtiles convert` | Small areas only; name the files `local-sat.pmtiles` / `local-topo.pmtiles` in `/srv/prepper/maps` |

After the Kolibri import, open `http://<box>:8070` once to create its admin account.

Your own books: any `.zim` file dropped in `/srv/prepper/zim` shows up in the library within ten
minutes. To turn your own PDFs or web pages into one, see `zimwriterfs` (installed by setup) and
`stack/shelf/build.py` as an example. Only add things you have the right to copy.

## Optional

- **Its own Wi-Fi.** With a USB Wi-Fi adapter plugged in: `sudo /opt/prepper/hotspot/install.sh`.
  Outside the US add `COUNTRY=GB` (your country code). Phones join the `prepper` network and the
  start page pops up (http://10.42.0.1). No internet is
  passed through.
- **Backup to a USB drive.** Format the drive ext4 with the label `prepper-usb`, then add
  `LABEL=prepper-usb /srv/usb ext4 defaults,nofail,x-systemd.automount,x-systemd.device-timeout=10s 0 2`
  to `/etc/fstab`, `sudo mkdir /srv/usb && sudo systemctl daemon-reload`, and
  `echo '30 3 * * * root /opt/prepper/backup-usb.sh' | sudo tee /etc/cron.d/prepper-backup`.
  `RESTORE.txt` on the drive says how to run the whole thing from it on another Linux PC.
  Books in `/srv/usb/extra/zim` are served too.
- **A different AI model.** `sudo MODEL=qwen3:4b ./setup.sh`. 3B to 4B models answer at a few
  words a second on a 2013 laptop-class CPU; bigger ones are too slow without a GPU.

## Undo

- Everything: `cd /opt/prepper && sudo docker compose down`, then
  `sudo rm -rf /opt/prepper /etc/cron.d/prepper /etc/cron.d/prepper-backup`. Content in
  `/srv/prepper` is left alone; delete it to get the space back.
- Hotspot: see the rollback line at the top of `stack/hotspot/install.sh`.

## Content and licences

This repo (scripts, pages, configs) is MIT. It downloads content made by others, each under its own
licence: Kiwix ZIMs (mostly CC BY-SA, from the Wikimedia and Stack Exchange communities and others),
OpenStreetMap data (ODbL) via Protomaps, Photon/GraphHopper geocoding data, Kolibri channels (each
channel lists its licence), and US-government public-domain documents. Map fonts and icons come
from protomaps/basemaps-assets (OFL). AI models come from Ollama's library under their makers'
licences. The ham pack quotes the eCFR (public domain) and summarises ARRL and ITU material with
citations; check rules against the current FCC text before relying on them.

Not medical, legal or radio-licensing advice. A small AI is often wrong: check anything important
against the library.
