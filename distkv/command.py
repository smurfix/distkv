# command line interface

import os
import sys
import trio_click as click
from pprint import pprint
import json
from functools import partial

from .util import (
    attrdict,
    combine_dict,
    PathLongener,
    MsgReader,
    PathShortener,
    split_one,
    NotGiven,
)
from .client import open_client, StreamedRequest
from .default import CFG
from .server import Server

from .auth import loader, gen_auth
from .exceptions import ClientError, ServerError

import logging
from logging.config import dictConfig

logger = logging.getLogger(__name__)


class Loader(click.Group):
    """
    A Group that can load additional commands from a subfolder.

    Caller:

        from distkv.command import Loader
        from functools import partial

        @click.command(cls=partial(Loader,__file__,'commands'))
        async def cmd()
            print("I am the main program")

    Sub-Command Usage (``main`` is defined for you), e.g. in ``commands/subcmd.py``::

        from distkv.command import Loader
        from functools import partial

        @main.command / group()
        async def cmd(self):
            print("I am", self.name)  # prints "subcmd"
    """
    def __init__(self, current_file, plugin_folder, *a, **kw):
        self.__plugin_folder = os.path.join(os.path.dirname(current_file), plugin_folder)
        super().__init__(*a, **kw)

    def list_commands(self, ctx):
        rv = []
        for filename in os.listdir(self.__plugin_folder):
            if filename.endswith('.py'):
                rv.append(filename[:-3])
        rv.sort()

        rv += super().list_commands(ctx)
        return rv

    def get_command(self, ctx, name):
        fn = os.path.join(self.__plugin_folder, name + '.py')
        if os.path.exists(fn):
            ns = {'main': self, '__file__':fn}
            with open(fn) as f:
                code = compile(f.read(), fn, 'exec')
                eval(code, ns, ns)
            try:
                cmd = ns['cli']
            except KeyError:
                raise SyntaxError("%r in %r doesn't define 'cli'" % (name,self.__plugin_folder))
            cmd.name = name
            return cmd
        else:
            return super().get_command(ctx, name)


def cmd():
    """
    The main command entry point, as declared in ``setup.py``.
    """
    try:
        main(standalone_mode=False)
    except click.exceptions.MissingParameter as exc:
        print("You need to provide an argument '%s'.\n" % (exc.param.name.upper()), file=sys.stderr)
        print(exc.cmd.get_help(exc.ctx), file=sys.stderr)
        sys.exit(2)
    except click.exceptions.UsageError as exc:
        try:
            s = str(exc)
        except TypeError:
            logger.exception(repr(exc), exc_info=exc)
        else:
            print(s, file=sys.stderr)
        sys.exit(2)
    except click.exceptions.Abort:
        print("Aborted.", file=sys.stderr)
        pass
    except (EnvironmentError, ClientError, ServerError) as err:
        print(type(err).__name__ + ":", *err.args, file=sys.stderr)
        sys.exit(1)
    except BaseException as exc:
        raise
        # print(exc)
        # sys.exit(1)


@click.command(cls=partial(Loader,__file__, 'commands'))
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Enable debugging. Use twice for more verbosity.",
)
@click.option(
    "-l", "--log", multiple=True, help="Adjust log level. Example: '--log asyncserf.actor=DEBUG'."
)
@click.option(
    "-q", "--quiet", count=True, help="Disable debugging. Opposite of '--verbose'."
)
@click.option(
    "-D", "--debug", is_flag=True, help="Enable debug speed-ups (smaller keys etc)."
)
@click.option("-c", "--cfg", type=click.File("r"), default=None, help="Configuration file (YAML).")
@click.option("-C", "--conf", multiple=True, help="Override a config entry. Example: '-C server.bind_default.port=57586'")
@click.pass_context
async def main(ctx, verbose, quiet, debug, log, cfg,conf):
    """
    This is the DistKV command. You need to add a subcommand for it to do
    anything.

    Default values for all configuration options are located in
    `distkv.default.CFG`.
    """
    ctx.ensure_object(attrdict)
    ctx.obj.debug = max(verbose - quiet + 1, 0)
    ctx.obj._DEBUG = debug
    
    if cfg:
        logger.debug("Loading %s", cfg)
        import yaml

        ctx.obj.cfg = combine_dict(yaml.safe_load(cfg), CFG, cls=attrdict)
        cfg.close()
    else:
        ctx.obj.cfg = CFG

    # One-Shot-Hack the config file.
    for k in conf:
        try:
            k,v = k.split('=')
        except ValueError:
            v = NotGiven
        else:
            try:
                v = eval(v)
            except Exception:
                pass
        c = ctx.obj.cfg
        *sl, s = k.split('.')
        for k in sl:
            c = c[k]
        if v is NotGiven:
            del c[s]
        else:
            c[s] = v

    # Configure logging. This is a somewhat arcane art.
    lcfg = ctx.obj.cfg.logging
    lcfg['root']['level'] = "DEBUG" if verbose > 2 else "INFO" if verbose > 1 else "WARNING" if verbose else "ERROR"
    for k in log:
        k,v = k.split('=')
        lcfg['loggers'].setdefault(k, {})['level'] = v
    dictConfig(lcfg)
    logging.captureWarnings(verbose > 0)


@main.command(short_help="Import the debugger",
        help="Imports PDB and then continues to process arguments.")
@click.argument("args", nargs=-1)
async def pdb(args):  # safe
    import pdb

    pdb.set_trace()  # safe
    if not args:
        return
    return await main.main(args)

