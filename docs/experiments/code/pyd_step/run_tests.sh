#!/usr/bin/env bash
# Regenerate results/D-logs/t*.txt. Run from the experiment root. Stores go to $S (default ../scratch_d).
set -u
S=${S:-../scratch_d}; L=results/D-logs; rm -rf "$S"; mkdir -p "$S" "$L"
BL="uv run python pyd_step/bl.py"; W=pyd_step/review_loop.py:workflow; P=pyd_step/wf_probes.py
I='{"topics":["a","b","c"],"max_rounds":2}'
clean() { sed "s#$PWD/##g"; }

{ echo '$ uv run python pyd_step/test_direct.py'; uv run python pyd_step/test_direct.py | tee "$S/direct.json"; } > $L/t1-direct.txt 2>&1

{ echo "\$ bl step $W --inputs '$I' --store \$S/t2h   (human mode, first step)"; $BL step $W --inputs "$I" --store "$S/t2h"; echo "exit=$?"
  echo "\$ orchestrator.py $W \$S/t2 '$I'"; uv run python pyd_step/orchestrator.py $W "$S/t2" "$I"; echo "exit=$?"; } 2>&1 | clean > $L/t2-orchestrated.txt
uv run python - "$S" >> $L/t2-orchestrated.txt <<'PY'
import json, sys
o = open("results/D-logs/t2-orchestrated.txt").read()
r = json.loads(o[o.index('{"status": "done"'):].splitlines()[0])["result"]
print("final result equal to the direct run's:", r == json.load(open(f"{sys.argv[1]}/direct.json")))
PY

{ echo '$ bl step wf_probes.py:repeat (fresh store)'; $BL step $P:repeat --store "$S/t3"; echo "exit=$?"
  for i in 1 2 3; do
    for k in $(ls "$S/t3"); do [ -e "$S/t3/$k/answer.md" ] || { echo "Paragraph $i-${k:0:4}" > "$S/a.txt"; $BL complete "${k:0:8}" "$S/a.txt" --store "$S/t3"; }; done
    echo "\$ bl step wf_probes.py:repeat (after completing every open call: round $i)"; $BL step $P:repeat --store "$S/t3"; echo "exit=$?"
  done
  echo '$ occurrence index per key'; (cd "$S/t3" && grep -H occurrence */call.json) | sed 's/^\(............\)[^/]*/\1/'; } 2>&1 | clean > $L/t3-repeat.txt

{ echo '$ bl step wf_probes.py:typed'; $BL step $P:typed --store "$S/t4"; echo "exit=$?"; K=$(ls "$S/t4"); KP=${K:0:6}
  for bad in 'not json' '{"accepted": "maybe"}' '{"problems": ["x"]}' '{"accepted": true, "problems": "x"}'; do
    echo "$bad" > "$S/bad.txt"; echo "\$ bl complete $KP <file: $bad>"; $BL complete $KP "$S/bad.txt" --store "$S/t4"; echo "exit=$? files now: $(ls "$S/t4/$K" | tr '\n' ' ')"; done
  echo '$ bl complete zzzz (unknown prefix)'; $BL complete zzzz "$S/bad.txt" --store "$S/t4"; echo "exit=$?"
  echo '$ bl complete 6 (ambiguous prefix, in the t2 store)'; $BL complete 6 "$S/bad.txt" --store "$S/t2"; echo "exit=$?"
  echo '{"accepted": false, "problems": ["vague"], "extra": 1}' > "$S/good.txt"
  echo "\$ bl complete $KP <file: {\"accepted\": false, \"problems\": [\"vague\"], \"extra\": 1}>"; $BL complete $KP "$S/good.txt" --store "$S/t4"; echo "exit=$? stored: $(cat "$S/t4/$K/answer.json")"
  echo "\$ bl complete $KP again"; $BL complete $KP "$S/good.txt" --store "$S/t4"; echo "exit=$?"
  echo '$ bl step wf_probes.py:typed (replay)'; $BL step $P:typed --store "$S/t4"; echo "exit=$?"; } 2>&1 | clean > $L/t4-typed.txt

{ echo "\$ orchestrator.py $W \$S/t5 '$I' --fail writer:b"; uv run python pyd_step/orchestrator.py $W "$S/t5" "$I" --fail writer:b; echo "exit=$?"
  echo '$ bl step (human mode, same store)'; $BL step $W --inputs "$I" --store "$S/t5"; echo "exit=$?"
  echo '$ store contents'; for d in "$S"/t5/*/; do echo "$(basename $d | cut -c1-12) $(grep -o '"agent": "[a-z]*"' $d/call.json) $(ls $d | tr '\n' ' ')"; done; } 2>&1 | clean > $L/t5-fail.txt

{ for f in sleepy threaded stuck; do echo "\$ bl step wf_probes.py:$f (fresh store)"; /usr/bin/time -f "wall %es" $BL step $P:$f --store "$S/t6-$f"; echo "exit=$?"; done
  echo x > "$S/x.txt"; $BL complete 866c32 "$S/x.txt" --store "$S/t6-stuck"
  echo '$ bl step wf_probes.py:stuck (after completing the open call)'; $BL step $P:stuck --store "$S/t6-stuck"; echo "exit=$?"
  echo "\$ bl step wf_probes.py:socket_io_cached --inputs '{\"delay\": 0.5}' (fresh store)"; /usr/bin/time -f "wall %es" $BL step $P:socket_io_cached --inputs "{\"delay\": 0.5}" --store "$S/t6-sockc"; echo "exit=$?"
  for d in 0.05 0.5; do echo "\$ bl step wf_probes.py:socket_io --inputs '{\"delay\": $d}' (fresh store)"; /usr/bin/time -f "wall %es" $BL step $P:socket_io --inputs "{\"delay\": $d}" --store "$S/t6-sock$d"; echo "exit=$?"; done; } 2>&1 | clean > $L/t6-quiescence.txt

rm -rf "$S/mid"; cp -r "$S/t2" "$S/mid"; for d in "$S"/mid/*/; do grep -q '"reviewer"' $d/call.json && rm -f $d/answer.json; done
{ echo '$ python -X dev -W always bl.py step (mid state: 3 reviewer calls open)'; uv run python -X dev -W always pyd_step/bl.py step $W --inputs "$I" --store "$S/mid" >/dev/null 2>"$S/err.txt"; echo "exit=$? stderr bytes=$(wc -c < "$S/err.txt")"
  echo '$ 30 replays each; md5 of stdout | sort | uniq -c'
  for st in t2 mid; do for m in "" --json; do for i in $(seq 30); do $BL step $W --inputs "$I" --store "$S/$st" $m | md5sum; done | sort | uniq -c | sed "s/^/store=$st mode=${m:-human}: /"; done; done
  echo '$ 30 fresh stores, first two steps each (every writer answered 'Paragraph' via bl complete): md5 of the sorted key list after step 2'
  for i in $(seq 30); do rm -rf "$S/f"; $BL step $W --inputs "$I" --store "$S/f" >/dev/null; for k in $(ls "$S/f"); do echo "Paragraph" > "$S/a.txt"; $BL complete ${k:0:8} "$S/a.txt" --store "$S/f"; done; $BL step $W --inputs "$I" --store "$S/f" --json | md5sum; done | sort | uniq -c; } 2>&1 | clean > $L/t7-determinism.txt

{ echo '$ bl step wf_probes.py:tooled'; $BL step $P:tooled --store "$S/t8"; echo "exit=$?"; cat "$S"/t8/*/prompt.md
  echo; echo '$ cat <reviewer prompt.md from the t2 store, a review of topic b>'; grep -l 'about b\.$' "$S"/t2/*/prompt.md | xargs grep -l reviewer | head -1 | xargs cat; } 2>&1 | clean > $L/t8-prompts.txt

O="$S/ops-bl"; mkdir -p "$O"; OI="{\"log\": \"$O/cached.log\", \"plain_log\": \"$O/unwrapped.log\", \"topics\": [\"a\", \"c\"]}"
{ echo '$ orchestrator.py pyd_step/wf_ops.py:workflow $S/ops-bl/store {log, plain_log, topics: [a, c]}'; uv run python pyd_step/orchestrator.py pyd_step/wf_ops.py:workflow "$O/store" "$OI"; echo "exit=$?"
  echo '$ bl step (one extra replay of the finished run)'; $BL step pyd_step/wf_ops.py:workflow --inputs "$OI" --store "$O/store" --json; echo "exit=$?"
  echo '--- cached.log (append_line_cached, publish: @cached)'; cat "$O/cached.log"
  echo '--- unwrapped.log (append_line called directly)'; cat "$O/unwrapped.log"
  echo '--- cached operations recorded in the store'; for d in "$O"/store/*/; do grep -q '"kind": "op"' $d/call.json && echo "$(basename $d | cut -c1-12) $(grep -o '"op": "[^"]*"' $d/call.json) -> $(cat $d/answer.json)"; done
  echo; echo '$ test_ops_direct.py (direct Pydantic AI run: no store, then twice with use_store)'; uv run python pyd_step/test_ops_direct.py "$S/ops-direct"
  echo; for i in 1 2 3; do echo "\$ bl step wf_ops.py:flaky (attempt $i)"; $BL step pyd_step/wf_ops.py:flaky --inputs "{\"marker\": \"$S/flaky.marker\"}" --store "$S/flaky"; echo "exit=$?"; done; } 2>&1 | clean > $L/t9-cached-ops.txt
