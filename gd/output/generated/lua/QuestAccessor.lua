-- Auto-generated canonical Lua accessor for Quest
local GD = require("gd")
local _tbl = "Quest"

local RowMeta = {
  Id = function(s) return GD.I32(_tbl, 0, s) end,
  Title = function(s) return GD.Str(_tbl, 1, s) end,
  Description = function(s) return GD.Str(_tbl, 2, s) end,
  RewardItemId = function(s) return GD.I32(_tbl, 3, s) end,
  Item = function(s) local rid = GD.I32(_tbl, 3, s) return ItemAccessor.ByID(rid) end,
  RequiredLevel = function(s) return GD.I32(_tbl, 4, s) end,
  Test = function(s) local n = GD.VecLen(_tbl, 5, s) local out = {} for i = 1, n do out[i] = GD.VecF64(_tbl, 5, s, i - 1) end return out end,
}

local M = {}
function M.Count() return GD.Count(_tbl) end
function M.ByIndex(i) return setmetatable({_row = GD.ByIndex(_tbl, i)}, RowMeta) end
function M.ByID(id) return setmetatable({_row = GD.ByID(_tbl, id)}, RowMeta) end
return M