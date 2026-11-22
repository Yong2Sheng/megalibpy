"""Standalone ROOT reader, executed by the selected ROOT Python, never imported.

Only stdlib and PyROOT are used here. This file must work in Python 3.10 even
when the calling analysis process uses a different Python version.
"""

import json
import math
import sys
from urllib.parse import quote


def _children(objects):
    objects = list(objects)
    names = [str(obj.GetName()) for obj in objects]
    occurrences = {}
    for obj, name in zip(objects, names):
        occurrences[name] = occurrences.get(name, 0) + 1
        part = quote(name, safe="") or "@unnamed"
        if names.count(name) > 1:
            part += "[{}]".format(occurrences[name])
        yield part, obj


def _axis(axis):
    n = axis.GetNbins()
    return {"title": str(axis.GetTitle()),
            "edges": [axis.GetBinLowEdge(i) for i in range(1, n + 1)]
            + [axis.GetBinUpEdge(n)]}


def _mapping(hist, siblings):
    """Recognize the explicit linear longitude TGaxis in rectangular images.

    Hammer images have no such axis. Unknown mappings remain unknown; neither
    histogram names nor the sign of a longitude determine coordinate meaning.
    """
    if hist.GetDimension() != 2:
        return None
    if str(hist.GetYaxis().GetTitle()).lower() != "galactic latitude [deg]":
        return None
    x, y = hist.GetXaxis(), hist.GetYaxis()
    mappings = []
    for obj in siblings:
        if not obj.InheritsFrom("TGaxis"):
            continue
        if str(obj.GetTitle()).lower() != "galactic longitude [deg]":
            continue
        if obj.GetFunction():
            continue  # Nonlinear/custom functions cannot be treated as affine.
        if "G" in str(obj.GetOption()).upper():
            continue  # Logarithmic TGaxis is not a linear coordinate mapping.
        near = lambda a, b: math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
        if not (near(obj.GetY1(), y.GetXmin()) and near(obj.GetY2(), y.GetXmin())):
            continue
        endpoints = sorted([obj.GetX1(), obj.GetX2()])
        if not (near(endpoints[0], x.GetXmin()) and near(endpoints[1], x.GetXmax())):
            continue
        if obj.GetX1() == obj.GetX2():
            continue
        scale = (obj.GetWmax() - obj.GetWmin()) / (obj.GetX2() - obj.GetX1())
        mappings.append({"scale": scale,
                         "offset": obj.GetWmin() - scale * obj.GetX1(),
                         "axis_title": str(obj.GetTitle()),
                         "coordinate_system": "galactic", "projection": "rectangular"})
    return mappings[0] if len(mappings) == 1 else None


def read(request):
    import ROOT

    ROOT.PyConfig.IgnoreCommandLineOptions = True
    ROOT.gROOT.SetBatch(True)
    root_file = ROOT.TFile.Open(request["path"], "READ")
    if not root_file or root_file.IsZombie():
        raise ValueError("Cannot open ROOT file")
    found = []
    retained = []  # Keep all deserialized owners alive until values are copied.

    def walk(obj, path, siblings=()):
        retained.append(obj)
        if obj.InheritsFrom("TH1"):
            dimension = int(obj.GetDimension())
            # Profiles store means, not counts or image intensity samples.
            if dimension in (1, 2) and not obj.InheritsFrom("TProfile") and not obj.InheritsFrom("TProfile2D"):
                found.append((obj, {"object_path": path, "name": str(obj.GetName()),
                                   "class_name": str(obj.ClassName()),
                                   "title": str(obj.GetTitle()), "dimension": dimension,
                                   "x_title": str(obj.GetXaxis().GetTitle()),
                                   "y_title": str(obj.GetYaxis().GetTitle()),
                                   "z_title": str(obj.GetZaxis().GetTitle())}, siblings))
        elif obj.InheritsFrom("TDirectory"):
            # Include key cycles in the selection path: old cycles are candidates.
            for key in obj.GetListOfKeys():
                child = key.ReadObj()
                part = quote(str(key.GetName()), safe="") + ";" + str(key.GetCycle())
                walk(child, (path + "/" if path else "") + part)
        elif obj.InheritsFrom("TPad"):
            children = list(obj.GetListOfPrimitives())
            # Pad coordinates are logarithms on log axes; a TGaxis in that
            # space cannot establish an affine map from histogram bin centers.
            mapping_siblings = children if not (obj.GetLogx() or obj.GetLogy()) else ()
            for part, child in _children(children):
                walk(child, path + "/" + part, mapping_siblings)

    try:
        walk(root_file, "")
        if request["action"] == "list":
            return {"objects": [meta for _, meta, _ in found]}
        candidates = [(obj, meta, siblings) for obj, meta, siblings in found
                      if meta["dimension"] == request["dimension"]]
        selector = request.get("object_path")
        if selector is not None:
            candidates = [entry for entry in candidates if entry[1]["object_path"] == selector]
        if len(candidates) != 1:
            choices = [meta["object_path"] for _, meta, _ in found
                       if meta["dimension"] == request["dimension"]]
            raise ValueError("Expected exactly one matching histogram; select object_path from: "
                             + repr(choices))
        hist, meta, siblings = candidates[0]
        data = {"object": meta, "x": _axis(hist.GetXaxis()),
                "value_title": str(hist.GetYaxis().GetTitle())}
        nx = hist.GetNbinsX()
        if meta["dimension"] == 1:
            data["values"] = [hist.GetBinContent(i) for i in range(1, nx + 1)]
            data["flow_values"] = [hist.GetBinContent(0), hist.GetBinContent(nx + 1)]
        else:
            ny = hist.GetNbinsY()
            data["y"] = _axis(hist.GetYaxis())
            data["value_title"] = str(hist.GetZaxis().GetTitle())
            data["values"] = [[hist.GetBinContent(i, j) for j in range(1, ny + 1)]
                              for i in range(1, nx + 1)]
            data["mapping"] = _mapping(hist, siblings)
        return data
    finally:
        root_file.Close()


def main():
    try:
        with open(sys.argv[1], encoding="utf-8") as stream:
            request = json.load(stream)
        response = {"data": read(request)}
    except Exception as exc:
        response = {"error": type(exc).__name__ + ": " + str(exc)}
    with open(sys.argv[2], "w", encoding="utf-8") as stream:
        json.dump(response, stream)


if __name__ == "__main__":
    main()
