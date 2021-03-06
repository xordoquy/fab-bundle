import os

from fabric.api import task, env, run, local, put, cd, sudo
from fabric.contrib.files import exists

from .utils import die, err, yay, template


def postgres(cmd):
    db_user = '-U postgres'
    if hasattr(env, 'postgres'):
        if 'admin' in env.postgres:
            db_user = '-U %s' % env.postgres['admin']
        if 'hostname' in env.postgres:
            db_user += ' -h %s' % env.postgres['hostname']
    return run(cmd % db_user)


def choose_postgres_template():
    if 'gis' in env and env.gis is False:
        return 'template0'
    else:
        return 'template_postgis'


def database_creation():
    bundle_name = env.http_host
    installed_dbs = postgres('psql %s -l|grep UTF8')
    installed_dbs = [db.split('|')[0].strip() for db in installed_dbs.split('\n')]

    print installed_dbs

    db_template = choose_postgres_template()

    if env.databases:
        for database in env.databases.values():
            if database['NAME'] in installed_dbs:
                continue
            args = [
                '%s',
                '-T %s' % db_template,
                '-E UTF8',
            ]
            if 'USER' in database:
                args.append(' -O %s' % database['USER'])
            args.append(bundle_name)
            postgres('createdb ' + ' '.join(args))
    else:
        if bundle_name not in installed_dbs:
            postgres(('createdb %s -T %s '
                 '-E UTF8 %s') % ('%s', db_template, bundle_name))


def database_migration():
    bundle_name = env.http_host
    if 'migrations' in env:
        if env.migrations == 'nashvegas':
            manage('upgradedb -l', noinput=False)  # This creates the migration
                                                   # tables

            installed = postgres('psql %s %s -c "select id from '
                            'nashvegas_migration limit 1;"' % ('%s', bundle_name))
            installed = '0 rows' not in installed
            if installed:
                manage('upgradedb -e', noinput=False)
            else:
                # 1st deploy, force syncdb and seed migrations.
                manage('syncdb')
                manage('upgradedb -s', noinput=False)
        elif env.migrations == 'south':
            manage('syncdb')
            manage('migrate')
        else:
            die("%s is not supported for migrations." % env.migrations)

    else:
        manage('syncdb')


@task()
def deploy(force_version=None):
    """Deploys to the current bundle"""
    bundle_name = env.http_host
    bundle_root = '%s/%s' % (env.get('bundle_root', run('pwd') + '/bundles'),
                             bundle_name)
    env.bundle_root = bundle_root
    run('mkdir -p %s/{log,conf,public}' % bundle_root)

    # virtualenv, Packages
    if not exists(bundle_root + '/env'):
        run('virtualenv --no-site-packages %s/env' % bundle_root)
    run('%s/env/bin/pip install -U pip' % bundle_root)

    local('python setup.py sdist')
    dists = [
        d for d in os.listdir(os.path.join(os.getcwd(),
                                           'dist')) if d.endswith('.tar.gz')
    ]
    version_string = lambda d: d.rsplit('-', 1)[1][:-7]
    def int_or_s(num):
        try:
            return int(num)
        except ValueError:
            return num
    dist = sorted(dists, key=lambda d: map(int_or_s,
                                           version_string(d).split('.')))[-1]
    version = force_version or version_string(dist)
    dist_name = dist.rsplit('-', 1)[0]
    requirement = '%s==%s' % (dist_name, version)

    packages = env.bundle_root + '/packages'
    run('mkdir -p %s' % packages)
    if not exists('%s/%s' % (packages, dist)):
        put('dist/%s' % dist, '%s/%s' % (packages, dist))

    has_vendor = 'vendor' in os.listdir(os.getcwd())
    if has_vendor:
        local_files = set(os.listdir(os.path.join(os.getcwd(), 'vendor')))
        uploaded = set(run('ls %s' % packages).split())
        diff = local_files - uploaded
        for file_name in diff:
            put('vendor/%s' % file_name, '%s/%s' % (packages, file_name))

    freeze = run('%s/env/bin/pip freeze' % bundle_root).split()
    if requirement in freeze and force_version is None:
        die("%s is already deployed. Increment the version number to deploy "
            "a new release." % requirement)

    cmd = '%s/env/bin/pip install -U %s gunicorn gevent greenlet setproctitle --find-links file://%s' % (
        bundle_root, requirement, packages
    )
    if 'index_url' in env:
        cmd += ' --index-url %(index_url)s' % env
    run(cmd)
    env.path = bundle_root
    python = run('ls %s/env/lib' % bundle_root)
    template(
        'path_extension.pth',
        '%s/env/lib/%s/site-packages/_virtualenv_path_extensions.pth' % (
            bundle_root, python
        ),
    )

    env.media_root = bundle_root + '/public/media'
    env.static_root = bundle_root + '/public/static'
    if not 'staticfiles' in env:
        env.staticfiles = True
    if not 'cache' in env:
        env.cache = 0  # redis DB
    template('settings.py', '%s/settings.py' % bundle_root)
    template('wsgi.py', '%s/wsgi.py' % bundle_root)

    # Do we have a DB?
    database_creation()
    database_migration()

    if env.staticfiles:
        manage('collectstatic')

    # Some things don't like dots
    env.app = env.http_host.replace('.', '')

    # Cron tasks
    if 'cron' in env:
        template('cron', '%(bundle_root)s/conf/cron' % env, use_sudo=True)
        sudo('chown root:root %(bundle_root)s/conf/cron' % env)
        sudo('chmod 644 %(bundle_root)s/conf/cron' % env)
        sudo('ln -sf %(bundle_root)s/conf/cron /etc/cron.d/%(app)s' % env)
    else:
        # Make sure to deactivate tasks if the cron section is removed
        sudo('rm -f %(bundle_root)s/conf/cron /etc/cron.d/%(app)s' % env)

    # Log rotation
    logrotate = '/etc/logrotate.d/%(app)s' % env
    template('logrotate', logrotate, use_sudo=True)
    sudo('chown root:root %s' % logrotate)

    # Nginx vhost
    changed = template('nginx.conf', '%s/conf/nginx.conf' % bundle_root)
    with cd('/etc/nginx/sites-available'):
        sudo('ln -sf %s/conf/nginx.conf %s.conf' % (bundle_root,
                                                    env.http_host))
    with cd('/etc/nginx/sites-enabled'):
        sudo('ln -sf ../sites-available/%s.conf' % env.http_host)
    if 'ssl_cert' in env and 'ssl_key' in env:
        put(env.ssl_cert, '%s/conf/ssl.crt' % bundle_root)
        put(env.ssl_key, '%s/conf/ssl.key' % bundle_root)
    if changed:  # TODO detect if the certs have changed
        sudo('/etc/init.d/nginx reload')

    # Supervisor task(s) -- gunicorn + rq
    if not 'workers' in env:
        env.workers = 2
    changed = template('supervisor.conf',
                       '%s/conf/supervisor.conf' % bundle_root)
    with cd('/etc/supervisor/conf.d'):
        sudo('ln -sf %s/conf/supervisor.conf %s.conf' % (bundle_root,
                                                         bundle_name))

    if 'rq' in env and env.rq:
        changed = True  # Always supervisorctl update

        # RQ forks processes and they load the latest version of the code.
        # No need to restart the worker **unless** RQ has been updated (TODO).
        for worker_id in range(env.rq['workers']):
            env.worker_id = worker_id
            rq_changed = template(
                'rq.conf', '%s/conf/rq%s.conf' % (bundle_root, worker_id),
            )
            with cd('/etc/supervisor/conf.d'):
                sudo('ln -sf %s/conf/rq%s.conf %s_worker%s.conf' % (
                    bundle_root, worker_id, bundle_name, worker_id,
                ))

        # Scale down workers if the number decreased
        workers = run('ls /etc/supervisor/conf.d/%s_worker*.conf' % bundle_name)
        workers_conf = run('ls %s/conf/rq*.conf' % bundle_root)
        to_delete = []
        for w in workers.split():
            if int(w.split('%s_worker' % bundle_name, 1)[1][:-5]) >= env.rq['workers']:
                to_delete.append(w)
        for w in workers_conf.split():
            if int(w.split(bundle_name, 1)[1][8:-5]) >= env.rq['workers']:
                to_delete.append(w)
        if to_delete:
            sudo('rm %s' % " ".join(to_delete))

    if changed:
        sudo('supervisorctl update')
    run('kill -HUP `pgrep gunicorn`')

    # All set, user feedback
    ip = run('curl http://ifconfig.me/')
    dns = run('nslookup %s' % env.http_host)
    if ip in dns:
        proto = 'https' if 'ssl_cert' in env else 'http'
        yay("Visit %s://%s" % (proto, env.http_host))
    else:
        err("Deployment successful but make sure %s points to %s" % (
            env.http_host, ip))


@task()
def destroy():
    """Destroys the current bundle"""
    pass


def manage(command, noinput=True):
    """Runs a management command"""
    noinput = '--noinput' if noinput else ''
    run('%s/env/bin/django-admin.py %s %s --settings=settings' % (
        env.bundle_root, command, noinput,
    ))
