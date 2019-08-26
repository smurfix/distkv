# command line interface

import asyncclick as click
import yaml
import sys

from distkv.util import yprint, NotGiven

import logging

logger = logging.getLogger(__name__)


@main.group()  # pylint: disable=undefined-variable
@click.pass_obj
async def cli(obj):
    """Manage code stored in DistKV."""
    pass


@cli.command()
@click.option(
    "-s", "--script", type=click.File(mode="w", lazy=True), help="Save the code here"
)
@click.argument("path", nargs=-1)
@click.pass_obj
async def get(obj, path, script):
    """Read a code entry"""
    if not path:
        raise click.UsageError("You need a non-empty path.")
    res = await obj.client._request(
        action="get_value",
        path=obj.cfg["codes"]["prefix"] + path,
        iter=False,
        nchain=obj.meta,
    )
    if 'value' not in res:
        if obj.debug:
            print("No entry here.", file=sys.stderr)
        sys.exit(1)
    if not obj.meta:
        res = res.value
    if script:
        code = res.pop("code", None)
        if code is not None:
            print(code, file=script)
    yprint(res, stream=obj.stdout)


@cli.command()
@click.option("-a", "--async", "async_", is_flag=True, help="The code is async")
@click.option(
    "-t", "--thread", is_flag=True, help="The code should run in a worker thread"
)
@click.option("-s", "--script", type=click.File(mode="r"), help="File with the code")
@click.option("-v", "--vars", multiple=True, type=str, help="Required variables")
@click.option("-i", "--info", type=str, help="one-liner info about the code")
@click.option(
    "-d", "--data", type=click.File(mode="r"), help="load the metadata (YAML)"
)
@click.argument("path", nargs=-1)
@click.pass_obj
async def set(obj, path, thread, script, data, vars, async_, info):
    """Save Python code."""
    if async_:
        if thread:
            raise click.UsageError("You can't specify both '--async' and '--thread'.")
    else:
        if thread:
            async_ = False
        else:
            async_ = None

    if not path:
        raise click.UsageError("You need a non-empty path.")

    if data:
        msg = yaml.safe_load(data)
    else:
        msg = {}
    chain = NotGiven
    if "value" in msg:
        chain = msg.get("chain", NotGiven)
        msg = msg["value"]
    if async_ is not None or "is_async" not in msg:
        msg["is_async"] = async_

    if info is not None:
        msg["info"] = info

    if "code" in msg:
        if script:
            raise click.UsageError("Duplicate script")
    else:
        if not script:
            raise click.UsageError("Missing script")
        msg["code"] = script.read()

    if "vars" in msg:
        if vars:
            raise click.UsageError("Duplicate variables")
    elif vars:
        vl = msg['vars'] = []
        for vv in vars:
            vl.extend(vv.split(','))

    res = await obj.client.set(
        *obj.cfg["codes"]["prefix"],
        *path,
        value=msg,
        nchain=obj.meta,
        **({'chain':chain} if chain is not NotGiven else {}),
    )
    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.group("module")
@click.pass_obj
async def mod(obj):
    """
    Change the code of a module stored in DistKV
    """


@mod.command()
@click.option(
    "-s", "--script", type=click.File(mode="w", lazy=True), help="Save the code here"
)
@click.argument("path", nargs=-1)
@click.pass_obj  # pylint: disable=function-redefined
async def get(obj, path, script):
    """Read a module entry"""
    if not path:
        raise click.UsageError("You need a non-empty path.")
    res = await obj.client._request(
        action="get_value",
        path=obj.cfg["modules"]["prefix"] + path,
        iter=False,
        nchain=obj.meta,
    )
    if not obj.meta:
        res = res.value

    code = res.pop("code", None)
    if code is not None:
        code = code.rstrip('\n \t')+"\n"
        if script:
            print(code, file=script)
        else:
            res['code'] = code

    yprint(res, stream=obj.stdout)


@mod.command()
@click.option(
    "-s", "--script", type=click.File(mode="r"), help="File with the module's code"
)
@click.option(
    "-d", "--data", type=click.File(mode="r"), help="load the metadata (YAML)"
)
@click.argument("path", nargs=-1)  # pylint: disable=function-redefined
@click.pass_obj
async def set(obj, path, script, data):
    """Save a Python module to DistKV."""
    if not path:
        raise click.UsageError("You need a non-empty path.")

    if data:
        msg = yaml.safe_load(data)
    else:
        msg = {}
    chain = None
    if "value" in msg:
        chain = msg.get("chain", None)
        msg = msg["value"]

    if "code" not in msg:
        if script:
            raise click.UsageError("Duplicate script")
    else:
        if not script:
            raise click.UsageError("Missing script")
        msg["code"] = script.read()

    res = await obj.client.set(
        *obj.cfg["modules"]["prefix"],
        *path,
        value=msg,
        iter=False,
        nchain=obj.meta,
        chain=chain,
    )
    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command()
@click.option(
    "-d",
    "--as-dict",
    default=None,
    help="Structure as dictionary. The argument is the key to use "
    "for values. Default: return as list",
)
@click.option(
    "-m",
    "--maxdepth",
    type=int,
    default=None,
    help="Limit recursion depth. Default: whole tree",
)
@click.option(
    "-M",
    "--mindepth",
    type=int,
    default=None,
    help="Starting depth. Default: whole tree",
)
@click.option("-f", "--full", is_flag=True, help="print complete entries.")
@click.option("-s", "--short", is_flag=True, help="print shortened entries.")
@click.argument("path", nargs=-1)
@click.pass_obj
async def list(obj, path, as_dict, maxdepth, mindepth, full, short):
    """
    List code entries.

    If you read a sub-tree recursively, be aware that the whole subtree
    will be read before anything is printed. Use the "watch --state" subcommand
    for incremental output.
    """

    if (full or as_dict) and short:
        raise click.UsageError("'-f'/'-d' and '-s' are incompatible.")
    kw = {}
    if maxdepth is not None:
        kw["max_depth"] = maxdepth
    if mindepth is not None:
        kw["min_depth"] = mindepth
    y = {}
    async for r in obj.client.get_tree(*obj.cfg['codes'].prefix, *path, nchain=obj.meta, **kw):
        r.pop("seq", None)
        path = r.pop("path")
        if not full:
            if 'info' not in r.value:
                r.value.info = "<%d lines>" % (len(r.value.code.splitlines()),)
            del r.value['code']

        if short:
            print (' '.join(path),"::",r.value.info)
            continue

        if as_dict is not None:
            yy = y
            for p in path:
                yy = yy.setdefault(p, {})
            try:
                yy[as_dict] = r if obj.meta else r.value
            except AttributeError:
                continue
        else:
            y = {}
            try:
                y[path] = r if obj.meta else r.value
            except AttributeError:
                continue
            yprint([y], stream=obj.stdout)

    if as_dict is not None:
        yprint(y, stream=obj.stdout)
    return
