#!/usr/bin/env python3
from pathlib import Path

observer_path = Path('.github/workflows/junca-public-testnet-release-observer.yml')
test_path = Path('tests/test_junca_hardened_immutable_release_workflow.py')

observer = observer_path.read_text(encoding='utf-8')
old = '  group: junca-public-testnet-release-observer-${{ github.event.workflow_run.id }}-${{ github.event.action }}\n'
new = "  group: junca-public-testnet-release-observer-${{ github.event.action == 'completed' && 'terminal-publication' || github.event.workflow_run.id }}\n"
if observer.count(old) != 1:
    raise SystemExit('OBSERVER_CONCURRENCY_SIGNATURE_MISMATCH')
observer = observer.replace(old, new, 1)

start_marker = '          publish_failures=0\n'
end_marker = '          incident_comment_emitted=false\n'
start = observer.find(start_marker)
end = observer.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit(f'OBSERVER_TRANSITION_BOUNDARY_MISSING start={start} end={end}')
replacement = '''          publish_failures=0
          prior_current_state=""
          prior_phase=""
          prior_result=""
          if [ "$source_binding" = "EXACT_CURRENT_MAIN" ]; then
            prior_current_state="$(
              gh api "repos/${GITHUB_REPOSITORY}/issues/269" \
                --jq '.body // ""' 2>/dev/null || true
            )"
            prior_phase="$(
              sed -n 's/^- Phase: `\\([^`]*\\)`.*/\\1/p' \
                <<<"$prior_current_state" | head -1
            )"
            prior_result="$(
              sed -n 's/^- Result: \\*\\*\\([^*]*\\)\\*\\*.*/\\1/p' \
                <<<"$prior_current_state" | head -1
            )"
            if ! publish_with_retry PATCH "repos/${GITHUB_REPOSITORY}/issues/269"; then
              publish_failures=$((publish_failures + 1))
              echo "::warning title=Current-state publication deferred::Issue 269 update failed after bounded retries."
            fi
          fi

          hard_terminal_result=false
          case "$result" in
            REJECTED|TIMED_OUT|ACTION_REQUIRED) hard_terminal_result=true ;;
          esac

          hard_terminal_phase=false
          case "$phase" in
            IMMUTABLE_RELEASE_CHAIN|IMMUTABLE_RELEASE_CHAIN_V2|FINALITY_CONTINUITY_READBACK)
              hard_terminal_phase=true
              ;;
          esac

          state_transition=false
          if [ "$prior_phase" != "$phase" ] || [ "$prior_result" != "$result" ]; then
            state_transition=true
          fi

          incident_notification=false
          if [ "$source_binding" = "EXACT_CURRENT_MAIN" ] && \
             [ "$hard_terminal_result" = true ] && \
             [ "$hard_terminal_phase" = true ] && \
             [ "$state_transition" = true ]; then
            incident_notification=true
          fi

'''
observer = observer[:start] + replacement + observer[end:]
old_marker = '            incident_marker="<!-- junca-release-observer:${OBSERVED_RUN_ID}:${live_attempt}:${result} -->"\n'
new_marker = '            incident_marker="<!-- junca-release-observer:${OBSERVED_RUN_ID}:${result} -->"\n'
if observer.count(old_marker) != 1:
    raise SystemExit('OBSERVER_MARKER_SIGNATURE_MISMATCH')
observer = observer.replace(old_marker, new_marker, 1)
old_summary = '''            echo "- Incident notification eligible: ${incident_notification}"
            echo "- Incident comment emitted: ${incident_comment_emitted}"
'''
new_summary = '''            echo "- Prior phase: ${prior_phase:-NONE}"
            echo "- Prior result: ${prior_result:-NONE}"
            echo "- Terminal state transition: ${state_transition}"
            echo "- Incident notification eligible: ${incident_notification}"
            echo "- Incident comment emitted: ${incident_comment_emitted}"
'''
if observer.count(old_summary) != 1:
    raise SystemExit('OBSERVER_SUMMARY_SIGNATURE_MISMATCH')
observer = observer.replace(old_summary, new_summary, 1)
observer_path.write_text(observer, encoding='utf-8')

test = test_path.read_text(encoding='utf-8')
old_req = '            \'incident_marker="<!-- junca-release-observer:${OBSERVED_RUN_ID}:${live_attempt}:${result} -->"\',\n'
new_req = '''            "group: junca-public-testnet-release-observer-${{ github.event.action == 'completed' && 'terminal-publication' || github.event.workflow_run.id }}",
            'prior_current_state=""',
            'prior_phase=""',
            'prior_result=""',
            'state_transition=false',
            'hard_terminal_result=false',
            'hard_terminal_phase=false',
            'incident_marker="<!-- junca-release-observer:${OBSERVED_RUN_ID}:${result} -->"',
'''
if test.count(old_req) != 1:
    raise SystemExit('OBSERVER_TEST_REQUIRED_SIGNATURE_MISMATCH')
test = test.replace(old_req, new_req, 1)
anchor = "        self.assertNotIn('issues/${issue}/comments', self.observer_workflow)\n"
extra = anchor + '''        self.assertNotIn(
            'incident_marker="<!-- junca-release-observer:${OBSERVED_RUN_ID}:${live_attempt}:${result} -->"',
            self.observer_workflow,
        )
'''
if test.count(anchor) != 1:
    raise SystemExit('OBSERVER_TEST_NEGATIVE_SIGNATURE_MISMATCH')
test = test.replace(anchor, extra, 1)
test_path.write_text(test, encoding='utf-8')
