#!/usr/bin/env bash
# Schedule scripts/nightly.sh: daily at --at (local time, default 03:17).
#
#   scripts/install-nightly.sh --push              build and push to main every night
#   scripts/install-nightly.sh --branch B          build branch B, compare with main, push nothing
#   scripts/install-nightly.sh --remove            unschedule it
#
# It creates the job's own worktree (~/car-research-nightly) if missing and schedules that
# worktree's scripts/nightly.sh, which checks out origin/<branch> before every run.
#
# Windows (Git Bash): a Task Scheduler task, "car-research nightly", that runs Git's bash. It wakes
# the computer, runs as soon as it can after a missed start, stops after four hours, and runs as
# you while you are logged on (no stored password). Elsewhere: a line in your crontab.
set -euo pipefail

branch=main push="" at="03:17" remove=0
while [ $# -gt 0 ]; do
  case "$1" in
    --branch) branch="$2"; shift 2 ;;
    --push) push=" --push"; shift ;;
    --at) at="$2"; shift 2 ;;
    --remove) remove=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

repo=$(cd "$(dirname "$0")/.." && pwd)
worktree="${CAR_RESEARCH_WORKTREE:-$HOME/car-research-nightly}"
task="car-research nightly"

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    if [ "$remove" = 1 ]; then schtasks.exe //Delete //TN "$task" //F; exit 0; fi
    git -C "$repo" fetch -q origin
    [ -d "$worktree" ] || git -C "$repo" worktree add --detach "$worktree" "origin/$branch"
    # Git's bin/bash.exe sets up its environment before running the script; /usr/bin/bash otherwise.
    bash_exe=$(cygpath -w "$(cygpath -u "${PROGRAMFILES:-C:/Program Files}")/Git/bin/bash.exe")
    [ -f "$(cygpath -u "$bash_exe")" ] || bash_exe=$(cygpath -w "$(command -v bash)")
    script=$(cygpath -u "$worktree/scripts/nightly.sh")
    user="$USERDOMAIN\\$USERNAME"
    xml=$(mktemp --suffix .xml)
    # Task Scheduler's XML (UTF-16 is what schtasks expects) is the only way to set wake, catch-up and time limit.
    cat > "$xml.utf8" <<XML
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>car-research: scrape into the raw store, build from scratch$( [ -n "$push" ] && echo ", push the snapshot to main" || echo ", compare with main" ).</Description></RegistrationInfo>
  <Triggers><CalendarTrigger><StartBoundary>2026-01-01T${at}:00</StartBoundary><Enabled>true</Enabled>
    <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>${user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable><WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT4H</ExecutionTimeLimit><Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>${bash_exe}</Command>
    <Arguments>-l ${script} --branch ${branch}${push}</Arguments></Exec></Actions>
</Task>
XML
    iconv -f UTF-8 -t UTF-16 "$xml.utf8" > "$xml"
    schtasks.exe //Create //TN "$task" //XML "$(cygpath -w "$xml")" //F
    rm -f "$xml" "$xml.utf8"
    schtasks.exe //Query //TN "$task" //FO LIST | grep -E "TaskName|Next Run Time|Status" || true
    ;;
  *)
    line="${at#*:} ${at%%:*} * * * CAR_RESEARCH_RAW=\"${CAR_RESEARCH_RAW:-}\" \"$worktree/scripts/nightly.sh\" --branch $branch$push"
    current=$(crontab -l 2>/dev/null | grep -v 'scripts/nightly.sh' || true)
    if [ "$remove" = 1 ]; then printf '%s\n' "$current" | crontab -; exit 0; fi
    git -C "$repo" fetch -q origin
    [ -d "$worktree" ] || git -C "$repo" worktree add --detach "$worktree" "origin/$branch"
    printf '%s\n%s\n' "$current" "$line" | grep -v '^$' | crontab -
    echo "crontab: $line"
    ;;
esac
