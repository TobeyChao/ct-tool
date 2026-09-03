-- Auto-generated canonical Lua accessor for Item (v4)
local GD = require("gd")
local _tbl = "Item"

local RowMeta = {
  Id = function(s) return GD.I32(_tbl, 0, s) end,
  Name = function(s) return GD.Str(_tbl, 1, s) end,
  Price = function(s) return GD.I32(_tbl, 2, s) end,
  Rarity = function(s) return GD.I32(_tbl, 3, s) end,
  ItemTypeId = function(s) return GD.I32(_tbl, 4, s) end,
  DropRange = function(s) return GD.I32(_tbl, 5, s) end,
  Tags = function(s) return GD.I32(_tbl, 6, s) end,
}

local M = {}
function M.ByID(id) return setmetatable({_row = GD.ByID(_tbl, id)}, RowMeta) end
return M