"""Catch what py_compile cannot: names used but never defined, and calls whose
keyword arguments the target does not accept.

Written after shipping a NameError to production. An assert aborted an edit
script halfway, so _sv_sections started using `faded` while its signature and
its caller were never updated. py_compile passed — NameError is a runtime
failure — and the unit tests exec'd the new function in isolation, so nothing
ever exercised the wiring between them.

Scope-aware: a nested function can read names from the function that encloses
it. The first version of this file did not know that and reported 34 closures
as errors, which is its own lesson about trusting a green check.
"""
import ast, sys, builtins

def _bound_in(fn):
    """Names bound directly inside `fn`, NOT descending into nested functions."""
    out = {a.arg for a in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
    if fn.args.vararg: out.add(fn.args.vararg.arg)
    if fn.args.kwarg:  out.add(fn.args.kwarg.arg)

    def walk(node, top=False):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(child.name)          # the name is bound; the body is its own scope
                continue
            if isinstance(child, ast.Lambda):
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                out.add(child.id)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                for a in child.names:
                    out.add((a.asname or a.name).split(".")[0])
            elif isinstance(child, ast.ExceptHandler) and child.name:
                out.add(child.name)
            elif isinstance(child, ast.Global) or isinstance(child, ast.Nonlocal):
                out.update(child.names)
            walk(child)
    walk(fn, top=True)
    return out


def _loads_in(fn):
    """Name reads in `fn` itself, not descending into functions nested in it."""
    out = []
    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                out.append(child)
            walk(child)
    walk(fn)
    return out


def check(path):
    src = open(path).read()
    tree = ast.parse(src)
    problems = []

    module_names = set(dir(builtins))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                module_names.add((a.asname or a.name).split(".")[0])
    # module-level assignments only (not inside functions)
    def top_assigns(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    module_names.add(sub.id)
                elif isinstance(sub, ast.arg):
                    module_names.add(sub.arg)
    top_assigns(tree.body)

    # walk with a scope stack
    def visit(node, scopes):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = scopes + [_bound_in(child)]
                # Only this function's OWN reads. Descending into nested defs
                # here judged their names against the wrong scope — my second
                # version did exactly that and produced 69 false alarms.
                for n in _loads_in(child):
                    if not any(n.id in s for s in inner) and n.id not in module_names:
                        problems.append(f"{path}:{n.lineno}  {child.name}() reads "
                                        f"undefined name '{n.id}'")
                visit(child, inner)
            else:
                visit(child, scopes)
    visit(tree, [])

    funcs = {n.name: n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        fn = funcs.get(call.func.id)
        if fn is None or fn.args.kwarg is not None:
            continue
        accepted = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        for kw in call.keywords:
            if kw.arg and kw.arg not in accepted:
                problems.append(f"{path}:{call.lineno}  {call.func.id}(...) passes keyword "
                                f"'{kw.arg}' that the signature does not accept")
    return sorted(set(problems))

bad = []
for f in sys.argv[1:]:
    bad += check(f)
if bad:
    print(f"✘ {len(bad)} problema(s):")
    for b in bad[:30]:
        print("   ", b)
    sys.exit(1)
print("✔ fiação consistente — nenhum nome solto, nenhum kwarg inexistente")
