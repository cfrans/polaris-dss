"""Explicit administrative R001/R002 instrumentation; never approve or execute remediation."""
from dataclasses import dataclass
from pathlib import Path
import sys

from experiment.scenarios.service_controller import ScenarioError, main as controller_main


@dataclass
class ResourceTransport:
    runner: object
    scenario: str
    use_sudo: bool = True

    def __call__(self, action: str) -> None:
        if self.scenario not in {'disk_full', 'cpu_high'}:
            raise ValueError('unsupported resource scenario')
        allowed = {'check', 'inject', 'reset'}
        if self.scenario == 'disk_full':
            allowed.add('prepare')
        if action not in allowed:
            raise ValueError('unsupported resource action')
        name = 'disk' if self.scenario == 'disk_full' else 'cpu'
        script = Path(__file__).resolve().with_name(name + '_scenario.sh')
        seconds = 180 if action == 'prepare' else 30
        prefix = 'sudo -n ' if self.use_sudo else ''
        command = prefix + f'/usr/bin/timeout -k 5s {seconds}s /usr/bin/bash -s -- ' + action
        code, output, _ = self.runner(command, timeout=seconds + 10, input_data=script.read_bytes())
        marker = {'check':'ready', 'inject':'injected', 'reset':'reset', 'prepare':'prepared'}[action]
        if code != 0 or output.strip() != f'{name}: {marker}':
            raise ScenarioError(f'{name} {action} not confirmed (exit code {code})')


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in {'disk_full', 'cpu_high'}:
        print('Usage: python -m experiment.scenarios.resource_controller <disk_full|cpu_high> <run|reset|prepare> --help', file=sys.stderr)
        return 2
    return controller_main(args[1:], scenario=args[0])


if __name__ == '__main__':
    raise SystemExit(main())
