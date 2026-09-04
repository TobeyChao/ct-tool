-- Auto-generated canonical Lua accessor for UIConfig ()
local GD = require("gd")
local _tbl = "UIConfig"

local RowMeta = {
  Id = function(s) return GD.I32(_tbl, 0, s) end,
  Layer = function(s) return GD.I8(_tbl, 1, s) end,
  ResourceKey = function(s) return GD.Str(_tbl, 2, s) end,
  BlocksRaycast = function(s) return GD.I8(_tbl, 3, s) end,
  Stack = function(s) return GD.I8(_tbl, 4, s) end,
}

local M = {}
function M.Count() return GD.Count(_tbl) end
function M.ByIndex(i) return setmetatable({_row = GD.ByIndex(_tbl, i)}, RowMeta) end
function M.ByID(id) return setmetatable({_row = GD.ByID(_tbl, id)}, RowMeta) end
return M