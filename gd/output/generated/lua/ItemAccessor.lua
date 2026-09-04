-- Auto-generated canonical Lua accessor for Item
local GD = require("gd")
local _tbl = "Item"

local ItemDropRangeMeta = {
  Min = function(s) return GD.I32(_tbl, 0, s) end,
  Max = function(s) return GD.I32(_tbl, 1, s) end,
}

local RowMeta = {
  Id = function(s) return GD.I32(_tbl, 0, s) end,
  Name = function(s) return GD.Str(_tbl, 1, s) end,
  Price = function(s) return GD.F32(_tbl, 2, s) end,
  Rarity = function(s) return GD.I8(_tbl, 3, s) end,
  ItemTypeId = function(s) return GD.I32(_tbl, 4, s) end,
  ItemType = function(s) local rid = GD.I32(_tbl, 4, s) return ItemTypeAccessor.ByID(rid) end,
  DropRange = function(s) return setmetatable({_row = GD.Rec(_tbl, 5, s)}, ItemDropRangeMeta) end,
  Tags = function(s) local n = GD.VecLen(_tbl, 6, s) local out = {} for i = 1, n do out[i] = GD.VecI32(_tbl, 6, s, i - 1) end return out end,
}

local M = {}
function M.Count() return GD.Count(_tbl) end
function M.ByIndex(i) return setmetatable({_row = GD.ByIndex(_tbl, i)}, RowMeta) end
function M.ByID(id) return setmetatable({_row = GD.ByID(_tbl, id)}, RowMeta) end
return M