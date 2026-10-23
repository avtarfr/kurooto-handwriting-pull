# Handwriting from the cloud, a Kurooto add-on

Your tablet's notes app saves pages to a cloud folder (Google Drive, OneDrive, Dropbox, Nextcloud...). This copies
the new ones with [rclone](https://rclone.org) into Handwritten notes' folder, where Kurooto writes them out as
notes. It's for when that cloud folder isn't synced to this computer already.

- Every 2 hours: `rclone copy <your remote> <Handwritten notes' folder>`, only the kinds Handwritten notes reads
  (PDF, PNG, JPEG, WebP, HEIC) and only the folder's top level. Never `rclone sync`: nothing on this computer is
  ever deleted. New files start a scan at once.
- Skipped while the connection is metered (a phone's hotspot), on Linux with NetworkManager.

## Add it

```
kurooto addons add https://github.com/avtarfr/kurooto-handwriting-pull --ref v1.0.0
```

or Dashboard → Features → **Add-ons by link**; read the card, Add. Set up your cloud in rclone first
(`rclone config`, in a terminal), then Features → **Handwriting from the cloud** → **Set up** → the remote and
folder, e.g. `gdrive:Handwritten` → **Turn on**. It needs Handwritten notes on.

## Its card

| | |
|---|---|
| Adds | the feature `hw_pull`; the command `/hwpull`; the job `hw_pull:pull` |
| May reach | nothing on the internet itself |
| May start | `rclone` (goes online by itself, with its own sign-in: Kurooto can't see what it sends), `nmcli` |
| Runs code | yes: one Python file, run inside Kurooto |

## Commands and settings

`/hwpull` says when it last pulled and what; `/hwpull now` pulls now.

| Setting | Default | Effect |
|---|---|---|
| `hw_pull.remote` | empty | the rclone remote and folder, e.g. `gdrive:Handwritten` |
| `hw_pull.every` | `every 2h` | how often to look |
| `hw_pull.unmetered_only` | on | skip while the connection is metered |
| `hw_pull.timeout_min` | 30 | a pull that takes longer is stopped |

## What leaves your computer

Nothing is uploaded: rclone downloads your pages from your cloud with the sign-in you gave it. Kurooto never sees that
sign-in; `/egress` counts each pull as handed to rclone.

## Remove it

Turn it off, then `kurooto addons remove handwriting-pull` (`kurooto addons undo handwriting-pull` puts it back).

## Tests

Inside a Kurooto checkout, with this folder at `addons/handwriting-pull/`: `uv run pytest addons/handwriting-pull`.
Fake `rclone` and `nmcli` stand in.
