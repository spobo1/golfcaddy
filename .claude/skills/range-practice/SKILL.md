---
name: range-practice
description: Logs a golf practice session at the driving range shot by shot. For each shot it asks which club, how far it went and whether it was struck well (good, ok or mishit), keeps running club averages, and at the end gives the player a CSV log file to keep that grows session by session. Use this whenever the user says they're at the range or driving range, hitting balls, practising or warming up with their clubs, wants to track or log how far they hit each club, reports shots like "7 iron 150 good", or uploads a range-log CSV to continue their history, even if they don't ask for a log explicitly.
---

# Range practice log

The player is standing at a range bay with a club in one hand and their phone in the other. Everything here should cost them as little typing and reading as possible: one short question at a time, one-line replies, and shorthand accepted everywhere.

## Starting a session

1. If the player uploaded a range-log CSV (from an earlier session), read it. It's their history: you'll add today's shots to it at the end, and you can compare today with it. Mention briefly how many shots and which clubs it holds.
2. Ask what club they're starting with, and tell them they can answer shots in one go, e.g. **"7i 150 good"**.
3. Distances are **carry** unless the player says otherwise. Range targets are usually judged by where the ball lands, and range balls often roll oddly. If they say they're reading totals (with roll) from a launch monitor or range tracking, record `total` instead. Ask only if it's unclear.

Don't front-load more questions than that. The player wants to start hitting.

## Each shot

Every shot needs three things:

- **Club.** Remember the current club until they change it, so "150 good" or "again, 148 ok" means another shot with the same club. Accept any common name: "7i", "7 iron", "seven", "3 wood", "4 hybrid", "PW", "sand wedge", "driver". If they name a wedge by loft ("52°", "56"), ask once which of PW / GW / SW / LW it is in their bag, then record that club and put the loft in the notes.
- **Distance** in yards. If they give metres, convert to yards (× 1.094) and say so. If a number is implausible for the club (a 7 iron at 290, a driver at 40), ask whether it's right before recording it. Leave a genuinely short mishit alone.
- **Strike**: `good`, `ok` or `mishit`. Map what they say:
  - good: "good", "pured", "flush", "great", "solid", "nailed it", 👍
  - ok: "ok", "fine", "decent", "a bit thin", "slightly heavy", "meh"
  - mishit: "mishit", "topped", "fat", "chunked", "duffed", "shank", "sculled", "bad", 👎

  If they don't say, ask "Good, ok or mishit?". Don't guess, because it decides whether the shot counts toward the average.

If a message is missing a piece, ask for just that piece. If it has several shots ("7i 150 good, 148 ok, 139 mishit"), record them all.

Launch monitor readings are optional extras. If the player gives any (launch angle, ball speed, club speed, spin, apex, offline, and so on), keep them with the shot using the field names in the reference section below.

### Replying to a shot

One line: the shot, then that club's running average.

> 7 iron #4: 152, good. 7 iron average 149 (3 counted, 1 mishit left out).

Mishits stay in the log but are left out of averages, since a topped shot isn't how far the club goes. If the first few shots are all mishits, the average line can say "no clean shots yet".

Every 10 shots or so, or when they switch clubs, you can add one short line of useful pattern if there is one ("Your good 7 irons are all 148–155; the ok ones come up about 10 short."). Don't do it every shot.

### Other things the player might say

- **"undo", "scratch that", "delete last"**: remove the last shot and confirm which one.
- **"change club", "now 9 iron", "switching to driver"**: switch; the next shots use the new club.
- **"summary", "how am I doing"**: show the summary table (see below) for the session so far.
- **"done", "finished", "that's it"**: end the session (below).

Keep your own numbered list of the shots in the conversation (club, distance, strike, any notes or readings), so nothing is lost if the session runs long.

## Ending the session

1. Write the session to a JSON file in this shape:

   ```json
   {"date": "YYYY-MM-DD", "time": "HH:MM", "distance_type": "carry",
    "shots": [{"club": "7 iron", "distance": 152, "strike": "good", "notes": ""},
              {"club": "7 iron", "distance": 139, "strike": "mishit", "notes": "topped",
               "launch_angle_deg": 9.5}]}
   ```

   Use today's date and roughly when the session started. Leave the time blank if you don't know it.

2. Run the bundled script. It writes the combined log (history first, then today) and prints a Markdown summary:

   ```bash
   python scripts/range_log.py --session session.json --out range-log.csv [--history <uploaded CSV>]
   ```

   Write `range-log.csv` wherever this environment puts files for the user to download (for example the outputs folder), and share it with them as a file.

3. Show the summary table the script printed. Add a sentence or two on what stands out: most consistent club, clubs with many mishits, big changes from their history. Keep it to what the numbers show.

4. Tell the player to **save `range-log.csv` and upload it at the start of the next session**, so the history keeps growing in one file. If they use the golfcaddy tools, the same file loads into clubtracker, and the caddy then uses their real distances:

   ```bash
   python -m clubtracker import --db shots.db --user <name> range-log.csv
   ```

If the player leaves without saying "done", offer to wrap up whenever they come back to the conversation. The shots are only saved once they have the file.

## Reference: CSV columns

`shot_id, date, time, club, distance_yd, distance_type, strike, notes`, then optional launch monitor readings:
`ball_speed_mph, club_speed_mph, smash_factor, launch_angle_deg, launch_direction_deg, spin_rate_rpm, spin_axis_deg, attack_angle_deg, club_path_deg, face_angle_deg, apex_yd, descent_angle_deg, offline_yd`.
Horizontal angles and offline distance are positive to the right of the target. The script fills in `shot_id` (date, session number and shot number) and writes club names in a standard form ("7 iron", "3 wood", "PW").
