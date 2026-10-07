"""Synthetic resource instrumentation checks; never touch laboratory hosts."""
from dataclasses import replace
from datetime import timedelta

import pytest

from experiment.scenarios.resource_controller import ResourceTransport, main
from experiment.scenarios import service_controller as controller
from experiment.verify.resource_watcher import resource_probe, watch_resource_round
from experiment.verify.service_watcher import ObservationError, observe_recovery
from src.tests.test_experiment import Clock, START, Connection as StoreConnection
from src.tests.test_service_controller import Connection, Observer
from src.tests.test_rounds import METADATA, round_row
from src.engine.script_catalog import load_catalog


@pytest.mark.parametrize('scenario,rule', [('disk_full','R001'),('cpu_high','R002')])
def test_resource_lifecycle_commits_before_injection_and_keeps_manual_fields(scenario,rule):
    connection, events = Connection(), []
    metadata=replace(METADATA,scenario=scenario)
    def action(operation):
        if operation=='inject':
            assert connection.events[-1]=='commit'
        events.append(operation)
    run_id,_=controller.run_round(connection,metadata,action,lambda: True,Observer(events),
                                scenario=scenario,sleep=lambda _: None)
    assert run_id==1
    assert events==['check','check',('observe',1),'inject','wait','stop_observer']
    assert connection.row['resolvido'] is None
    assert not any('decisao_humana' in sql or 'SET resolvido' in sql for sql,_ in connection.calls)


@pytest.mark.parametrize('scenario',['disk_full','cpu_high'])
def test_resource_reset_requires_closed_round_and_preserves_evidence(scenario):
    connection=Connection(row=round_row(cenario=scenario,resolvido=False))
    actions=[]
    original=connection.row.copy()
    controller.reset_round(connection,1,METADATA.target,actions.append,lambda: True,scenario=scenario)
    assert actions==['reset'] and connection.row==original
    connection.row['resolvido']=None
    with pytest.raises(controller.ScenarioError):
        controller.reset_round(connection,1,METADATA.target,actions.append,lambda: True,scenario=scenario)
    assert actions==['reset']


@pytest.mark.parametrize('scenario,output,code,healthy',[
    ('cpu_high','uso de CPU: 69% (limite 70%)',0,True),
    ('cpu_high','uso de CPU: 70% (limite 70%)',1,False),
    ('disk_full','uso de /mnt/polaris_test: 84% (limite 85%)',0,True),
    ('disk_full','uso de /mnt/polaris_test: 85% (limite 85%)',1,False),
])
def test_resource_probe_validates_both_output_and_exit_without_sudo(scenario,output,code,healthy):
    calls=[]
    def runner(command,timeout,input_data):
        calls.append(command)
        return code,output,' '
    assert resource_probe(runner,load_catalog(),scenario) is healthy
    assert 'sudo' not in calls[0]


@pytest.mark.parametrize('code,output',[(124,''),(0,'usage'),(1,'uso de CPU: 1% (limite 70%)'),
                                     (0,'uso de CPU: 110% (limite 70%)')])
def test_resource_probe_does_not_turn_verifier_errors_into_failure_or_recovery(code,output):
    with pytest.raises(ObservationError):
        resource_probe(lambda *a,**kw:(code,output,''),load_catalog(),'cpu_high')


def test_cpu_requires_thirty_seconds_below_limit_then_three_qualifying_checks():
    clock,recorded=Clock(),[]
    def probe():
        return clock.elapsed>0
    timestamp=observe_recovery(probe,clock.utc_now,recorded.append,40,healthy_duration=30,
                               monotonic=clock.monotonic,sleep=clock.sleep)
    assert timestamp==START+timedelta(seconds=31)
    assert clock.elapsed==33
    assert recorded==[timestamp]


def test_cpu_oscillation_restarts_entire_thirty_second_window():
    clock,recorded=Clock(),[]
    def probe():
        return clock.elapsed not in (0,20)
    timestamp=observe_recovery(probe,clock.utc_now,recorded.append,60,healthy_duration=30,
                               monotonic=clock.monotonic,sleep=clock.sleep)
    assert timestamp==START+timedelta(seconds=51)
    assert clock.elapsed==53


@pytest.mark.parametrize('scenario,timeout',[('disk_full',10),('cpu_high',40)])
def test_resource_observer_writes_only_t5_for_its_own_scenario(scenario,timeout):
    connection=StoreConnection()
    connection.row['cenario']=scenario
    clock=Clock()
    timestamp=watch_resource_round(connection,1,'target',lambda: clock.elapsed>0,timeout,
                                   scenario=scenario,monotonic=clock.monotonic,sleep=clock.sleep)
    updates=[(sql,args) for sql,args in connection.calls if sql.startswith('UPDATE')]
    assert len(updates)==1
    assert 'SET ts_verificado_ok' in updates[0][0] and 'resolvido IS NULL' in updates[0][0]
    assert updates[0][1][-1]==scenario
    assert 'pg_advisory_unlock' in connection.calls[-1][0]


def test_resource_observer_refuses_different_scenario_without_probing():
    with pytest.raises(ObservationError):
        watch_resource_round(StoreConnection(),1,'target',lambda: pytest.fail('no probe'),20,scenario='disk_full')


def test_transport_uses_fixed_scripts_and_rejects_shell_arguments():
    calls=[]
    def runner(command,timeout,input_data):
        calls.append((command,timeout,input_data))
        return 0,'disk: injected',''
    transport=ResourceTransport(runner,'disk_full',use_sudo=False)
    transport('inject')
    assert calls[0][0].endswith('bash -s -- inject')
    assert b'/mnt/polaris_test' in calls[0][2]
    with pytest.raises(ValueError):
        transport('inject /')
    assert len(calls)==1


def test_cpu_rejects_disk_prepare_action():
    transport=ResourceTransport(lambda *a,**kw: pytest.fail('no runner'),'cpu_high')
    with pytest.raises(ValueError):
        transport('prepare')


@pytest.mark.parametrize('scenario',['disk_full','cpu_high'])
def test_resource_t0_is_committed_before_callback_in_real_postgresql(conn,scenario):
    from src.db.connection import conectar
    events=[]
    metadata=replace(METADATA,scenario=scenario)
    def action(operation):
        if operation=='inject':
            with conectar() as other:
                with other.cursor() as cursor:
                    cursor.execute('SELECT * FROM experiment_run')
                    row=cursor.fetchone()
                    assert row['cenario']==scenario and row['ts_injecao'] is not None
                    assert row['ts_verificado_ok'] is None and row['resolvido'] is None
        events.append(operation)
    run_id,_=controller.run_round(conn,metadata,action,lambda: True,Observer(events),
                                 scenario=scenario,sleep=lambda _: None)
    assert run_id>0 and 'reset' not in events
    with conn.cursor() as cursor:
        cursor.execute('SELECT * FROM audit_log')
        assert cursor.fetchall()==[]
    conn.rollback()


def test_cross_scenario_target_lock_refuses_second_controller_in_real_postgresql(conn):
    from src.db.connection import conectar
    with controller.target_lock(conn,METADATA.target):
        with conectar() as other:
            with pytest.raises(controller.ScenarioError,match='another controller'):
                controller.run_round(other,replace(METADATA,scenario='disk_full'),
                                     lambda _: pytest.fail('no remote action'),lambda: True,Observer([]),
                                     scenario='disk_full',sleep=lambda _: None)
    with controller.target_lock(conn,METADATA.target):
        pass


@pytest.mark.parametrize('scenario',['disk_full','cpu_high'])
def test_real_resource_observer_locks_round_and_preserves_manual_fields(conn,scenario):
    from src.db.connection import conectar
    from experiment.verify.service_watcher import RoundStore
    with conn.cursor() as cursor:
        cursor.execute('INSERT INTO experiment_run (cenario,braco,rodada,ts_injecao,host_alvo) '
                       'VALUES (%s,\'baseline\',1,clock_timestamp(),\'target\') RETURNING id',(scenario,))
        run_id=cursor.fetchone()['id']
    conn.commit()
    with conectar(autocommit=True) as first, conectar(autocommit=True) as second:
        store=RoundStore(first,run_id,scenario)
        store.claim('target')
        clock=Clock()
        with pytest.raises(ObservationError,match='another observer'):
            watch_resource_round(second,run_id,'target',lambda: True,50,scenario=scenario)
        store.release()
        timestamp=watch_resource_round(second,run_id,'target',lambda: clock.elapsed>0,50,
                scenario=scenario,monotonic=clock.monotonic,sleep=clock.sleep)
        with conn.cursor() as cursor:
            cursor.execute('SELECT ts_verificado_ok,resolvido,passos_manuais FROM experiment_run WHERE id=%s',(run_id,))
            assert cursor.fetchone()==dict(ts_verificado_ok=timestamp,resolvido=None,passos_manuais=None)
        conn.rollback()
        with pytest.raises(ObservationError,match='measured'):
            watch_resource_round(first,run_id,'target',lambda: pytest.fail('no probe'),10,scenario=scenario)


@pytest.fixture
def resource_shell(tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path
    bash=shutil.which('bash')
    if not bash:
        pytest.skip('bash unavailable; target scripts remain unvalidated')
    mount=tmp_path/'mount'
    mount.mkdir()
    bin_dir=tmp_path/'bin'
    bin_dir.mkdir()
    state=tmp_path/'unit'
    state.write_text('not-found')
    helper=bin_dir/'helper.py'
    helper.write_text('''import sys,os,pathlib,math
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
m=pathlib.Path(os.environ['TEST_MOUNT'])
s=pathlib.Path(os.environ['UNIT_STATE'])
if name=='id': print(os.environ.get('FAKE_UID','0'))
elif name=='nproc': print(os.environ.get('FAKE_CPUS','1'))
elif name=='mountpoint': sys.exit(int(os.environ.get('NO_MOUNT','0')))
elif name=='readlink': print(args[-1])
elif name=='stat':
    value=pathlib.Path(args[-1]).stat()
    field=args[1]
    data={'%d':('100' if os.environ.get('ROOT_DEVICE') else '200') if args[-1]!='/' else '100',
          '%h':value.st_nlink,'%u':0,'%a':oct(value.st_mode & 0o777)[2:],'%i':value.st_ino,'%s':value.st_size}
    print(data[field])
elif name=='df':
    total=int(os.environ.get('FAKE_TOTAL','2000000000'))
    used=sum(p.stat().st_size for p in m.iterdir() if p.name in ('polaris_r001_lab.log.gz','enchimento.bin'))
    available=total-100000000-used
    percent=math.ceil(used*100/(used+available))
    if '--output=size,used,avail,pcent' in args: print('Size Used Avail Use%'); print(total,used,available,str(percent)+'%')
    else: print('Use%'); print(str(percent)+'%')
elif name=='dd': sys.exit(0)  # Partial preparation: no random bytes are generated in these tests.
elif name=='gzip': sys.exit(0)
elif name=='find': print(args[0])
elif name=='fallocate':
    with open(args[-1],'r+b') as stream: stream.truncate(int(args[1]))
elif name=='pgrep': sys.exit(0 if os.environ.get('FOREIGN_STRESS') else 1)
elif name=='stress-ng': sys.exit(99)
elif name=='systemd-run':
    with open(os.environ['SHELL_CALLS'],'a') as stream: stream.write('start '+' '.join(args)+'\\n')
    s.write_text('active')
elif name=='systemctl':
    if args[0]=='show':
        if '--property=LoadState' in args: print('not-found' if s.read_text()=='not-found' else 'loaded')
        else: print(os.environ.get('UNIT_OWNER','Polaris R002 experiment instrumentation'))
    elif args[0]=='is-active': print('inactive' if s.read_text()=='not-found' else s.read_text()); sys.exit(0 if s.read_text()=='active' else 3)
    elif args[0]=='stop':
        with open(os.environ['SHELL_CALLS'],'a') as stream: stream.write('stop '+args[1]+'\\n')
        s.write_text('not-found')
    else: sys.exit(99)
else: sys.exit(99)
''')
    commands=('dd','id','nproc','mountpoint','readlink','stat','df','gzip','find','fallocate',
              'pgrep','stress-ng','systemd-run','systemctl')
    for name in commands:
        file=bin_dir/name
        file.write_text('#!'+sys.executable+'\n'+helper.read_text())
        file.chmod(0o700)
    archive=mount/'polaris_r001_lab.log.gz'
    with archive.open('wb') as stream:
        stream.truncate(400*1024*1024)
    manifest=mount/'.polaris-r001.state'
    manifest.write_text(f'polaris-r001-v1 200 {archive.stat().st_ino} 0\n')
    manifest.chmod(0o600)
    calls=tmp_path/'calls'
    def run(scenario,action,**overrides):
        name='disk' if scenario=='disk_full' else 'cpu'
        script=Path(__file__).resolve().parents[2]/'experiment'/'scenarios'/(name+'_scenario.sh')
        # Only test copies receive temporary paths and fake Linux utilities. Product scripts stay fixed.
        source=script.read_text().replace('mount=/mnt/polaris_test','mount='+str(mount))
        source=source.replace('/usr/bin/stress-ng',str(bin_dir/'stress-ng'))
        env=dict(os.environ,PATH=str(bin_dir)+os.pathsep+os.environ.get('PATH',''),
                 TEST_MOUNT=str(mount),UNIT_STATE=str(state),SHELL_CALLS=str(calls),**overrides)
        return subprocess.run([bash,'-s','--',action],input=source,env=env,capture_output=True,text=True)
    return run,mount,state,calls


def test_disk_shell_injection_and_reset_touch_only_tracked_fixture(resource_shell):
    run,mount,_,_=resource_shell
    assert run('disk_full','check').stdout=='disk: ready\n'
    injected=run('disk_full','inject')
    assert injected.returncode==0, injected.stderr
    assert injected.stdout=='disk: injected\n'
    assert (mount/'enchimento.bin').exists()
    (mount/'polaris_r001_lab.log.gz').unlink()  # Approved cleanup removes the synthetic compressed log.
    reset=run('disk_full','reset')
    assert reset.returncode==0, reset.stderr
    assert reset.stdout=='disk: reset\n'
    assert list(mount.iterdir())==[]


@pytest.mark.parametrize('unsafe',['unrelated','symlink','hardlink','root_device','absent','oversize','untracked','replacement','lost_found'])
def test_disk_shell_refuses_unsafe_environment_without_creating_filler(resource_shell,unsafe):
    import os
    run,mount,_,_=resource_shell
    archive=mount/'polaris_r001_lab.log.gz'
    env={}
    if unsafe=='unrelated': (mount/'important.log').write_text('preserve')
    elif unsafe=='symlink':
        archive.unlink(); archive.symlink_to(mount/'important.log')
    elif unsafe=='hardlink': os.link(archive,mount.parent/'external.gz')
    elif unsafe=='root_device': env['ROOT_DEVICE']='1'
    elif unsafe=='absent': env['NO_MOUNT']='1'
    elif unsafe=='oversize': env['FAKE_TOTAL']='10000000000'
    elif unsafe=='untracked': (mount/'.polaris-r001.state').unlink()
    elif unsafe=='replacement':
        # Force a different inode, avoiding immediate inode reuse on some filesystems.
        archive.rename(mount.parent/'original.gz')
        with archive.open('wb') as stream: stream.truncate(400*1024*1024)
    elif unsafe=='lost_found':
        (mount/'lost+found').mkdir(); (mount/'lost+found'/'evidence').write_text('keep')
    result=run('disk_full','inject',**env)
    assert result.returncode!=0
    assert not (mount/'enchimento.bin').exists()
    result=run('disk_full','reset',**env)
    assert result.returncode!=0
    assert archive.exists() or archive.is_symlink()


def test_cpu_shell_injects_fixed_owned_unit_then_reset_stops_only_that_unit(resource_shell):
    run,_,state,calls=resource_shell
    assert run('cpu_high','check').stdout=='cpu: ready\n'
    assert run('cpu_high','inject').stdout=='cpu: injected\n'
    assert state.read_text()=='active'
    assert run('cpu_high','reset').stdout=='cpu: reset\n'
    lines=calls.read_text().splitlines()
    assert '--unit=polaris-experiment-cpu.service' in lines[0]
    assert '--property=Restart=no' in lines[0] and '--property=Type=exec' in lines[0]
    assert '--cpu 1 --cpu-load 100 --timeout 3600s' in lines[0]
    assert lines[1]=='stop polaris-experiment-cpu.service'


@pytest.mark.parametrize('guard',['multiple_cpus','foreign_process','foreign_unit','unprivileged','bad_action'])
def test_cpu_shell_cannot_inject_or_stop_foreign_workload(resource_shell,guard):
    run,_,state,calls=resource_shell
    env={}
    action='inject'
    if guard=='multiple_cpus': env['FAKE_CPUS']='2'
    elif guard=='foreign_process': env['FOREIGN_STRESS']='1'
    elif guard=='foreign_unit': state.write_text('active');env['UNIT_OWNER']='foreign'
    elif guard=='unprivileged': env['FAKE_UID']='1000'
    elif guard=='bad_action': action='inject; stop other'
    assert run('cpu_high',action,**env).returncode!=0
    assert not calls.exists()
    if guard=='foreign_unit':
        assert run('cpu_high','reset',**env).returncode!=0
        assert not calls.exists()


@pytest.mark.parametrize('scenario',['disk_full','cpu_high'])
@pytest.mark.parametrize('arm',['baseline','hitl'])
def test_resource_cli_uses_matching_controller_and_independent_watcher(monkeypatch,tmp_path,capsys,scenario,arm):
    from contextlib import contextmanager
    settings=type('Settings',(),dict(target_ssh_host=METADATA.target,target_ssh_user='polaris',
        target_ssh_key_path=str(tmp_path/'service_key'),scripts_path=tmp_path,rules_path=tmp_path,schema_path=tmp_path))()
    monkeypatch.setattr(controller,'get_settings',lambda:settings)
    monkeypatch.setattr(controller,'load_catalog',lambda _:object())
    monkeypatch.setattr(controller,'load',lambda *a:type('KB',(),{'versao_kb':METADATA.kb_version})())
    monkeypatch.setattr(controller,'repository_revision',lambda:METADATA.commit_sha)
    monkeypatch.setattr(controller,'runner_ssh',lambda *a:lambda *a,**kw:None)
    @contextmanager
    def connect():
        yield object()
    monkeypatch.setattr(controller,'conectar',connect)
    def run(connection,metadata,admin,probe,observer,**kwargs):
        assert metadata.scenario==scenario and metadata.arm==arm
        assert isinstance(admin,ResourceTransport) and admin.scenario==scenario
        assert observer.watcher.keywords['scenario']==scenario
        assert kwargs['scenario']==scenario
        return 1,START
    monkeypatch.setattr(controller,'run_round',run)
    assert main([scenario,'run','--arm',arm,'--repetition','1','--operator','operator',
                 '--system-version','0.4.0','--timeout','40','--admin-user','administrator',
                 '--admin-key-file',str(tmp_path/'admin_key')])==0
    assert 'recovery_measured' in capsys.readouterr().out


@pytest.mark.parametrize('duration',[-1,float('nan'),float('inf')])
def test_invalid_cpu_window_refused_before_probe(duration):
    with pytest.raises(ValueError):
        observe_recovery(lambda:pytest.fail('no probe'),lambda:START,lambda _:None,40,healthy_duration=duration)


def test_disk_prepare_never_overwrites_existing_fixture(resource_shell):
    run,mount,_,_=resource_shell
    original=(mount/'.polaris-r001.state').read_text()
    assert run('disk_full','prepare').returncode!=0
    assert (mount/'.polaris-r001.state').read_text()==original


def test_incomplete_disk_preparation_keeps_manifest_and_can_be_explicitly_cleaned(resource_shell):
    run,mount,_,_=resource_shell
    (mount/'.polaris-r001.state').unlink()
    (mount/'polaris_r001_lab.log.gz').unlink()
    result=run('disk_full','prepare')
    assert result.returncode!=0
    assert (mount/'.polaris-r001.state').exists()
    assert (mount/'polaris_r001_lab.log.gz').stat().st_size==0
    assert not (mount/'enchimento.bin').exists()
    assert run('disk_full','reset').stdout=='disk: reset\n'
    assert list(mount.iterdir())==[]
