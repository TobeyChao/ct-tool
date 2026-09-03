-- Auto-generated canonical Lua accessor for Quest (v4)
local GD = require("gd")
local _tbl = "Quest"

local RowMeta = {
  Id = function(s) return GD.I32(_tbl, 0, s) end,
  Title = function(s) return GD.Str(_tbl, 1, s) end,
  Description = function(s) return GD.Str(_tbl, 2, s) end,
  RewardItemId = function(s) return GD.I32(_tbl, 3, s) end,
  RequiredLevel = function(s) return GD.I32(_tbl, 4, s) end,
}

local M = {}
function M.ByID(id) return setmetatable({_row = GD.ByID(_tbl, id)}, RowMeta) end
return M