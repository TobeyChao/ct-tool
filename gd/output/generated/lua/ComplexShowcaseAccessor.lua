-- Auto-generated canonical Lua accessor for ComplexShowcase
local GD = require("gd")
local _tbl = "ComplexShowcase"

local WorldPositionMeta = {
  X = function(s) return GD.F64(_tbl, 0, s) end,
  Y = function(s) return GD.F64(_tbl, 1, s) end,
  Z = function(s) return GD.F64(_tbl, 2, s) end,
  Space = function(s) return GD.I8(_tbl, 3, s) end,
  IsPrecise = function(s) return GD.I8(_tbl, 4, s) end,
}

local RewardDefinitionMeta = {
  Kind = function(s) return GD.I8(_tbl, 0, s) end,
  ItemIds = function(s) local n = GD.VecLen(_tbl, 1, s) local out = {} for i = 1, n do out[i] = GD.VecI32(_tbl, 1, s, i - 1) end return out end,
  Amounts = function(s) local n = GD.VecLen(_tbl, 2, s) local out = {} for i = 1, n do out[i] = GD.VecI32(_tbl, 2, s, i - 1) end return out end,
  Chance = function(s) return GD.F32(_tbl, 3, s) end,
  Bounds = function(s) return setmetatable({_row = GD.Rec(_tbl, 4, s)}, RewardBoundsMeta) end,
}

local RewardBoundsMeta = {
  Min = function(s) return GD.I32(_tbl, 0, s) end,
  Max = function(s) return GD.I32(_tbl, 1, s) end,
  Guaranteed = function(s) return GD.I8(_tbl, 2, s) end,
}

local RowMeta = {
  Id = function(s) return GD.I64(_tbl, 0, s) end,
  Code = function(s) return GD.I32(_tbl, 1, s) end,
  Weight = function(s) return GD.F32(_tbl, 2, s) end,
  PreciseValue = function(s) return GD.F64(_tbl, 3, s) end,
  IsEnabled = function(s) return GD.I8(_tbl, 4, s) end,
  DisplayName = function(s) return GD.Str(_tbl, 5, s) end,
  Rarity = function(s) return GD.I8(_tbl, 6, s) end,
  ItemTypeId = function(s) return GD.I32(_tbl, 7, s) end,
  ItemType = function(s) local rid = GD.I32(_tbl, 7, s) return ItemTypeAccessor.ByID(rid) end,
  Position = function(s) return setmetatable({_row = GD.Rec(_tbl, 8, s)}, WorldPositionMeta) end,
  Reward = function(s) return setmetatable({_row = GD.Rec(_tbl, 9, s)}, RewardDefinitionMeta) end,
  IntValues = function(s) local n = GD.VecLen(_tbl, 10, s) local out = {} for i = 1, n do out[i] = GD.VecI32(_tbl, 10, s, i - 1) end return out end,
  LongValues = function(s) local n = GD.VecLen(_tbl, 11, s) local out = {} for i = 1, n do out[i] = GD.VecI64(_tbl, 11, s, i - 1) end return out end,
  Ratios = function(s) local n = GD.VecLen(_tbl, 12, s) local out = {} for i = 1, n do out[i] = GD.VecF32(_tbl, 12, s, i - 1) end return out end,
  Precisions = function(s) local n = GD.VecLen(_tbl, 13, s) local out = {} for i = 1, n do out[i] = GD.VecF64(_tbl, 13, s, i - 1) end return out end,
  Flags = function(s) local n = GD.VecLen(_tbl, 14, s) local out = {} for i = 1, n do out[i] = GD.VecBool(_tbl, 14, s, i - 1) end return out end,
  Aliases = function(s) local n = GD.VecLen(_tbl, 15, s) local out = {} for i = 1, n do out[i] = GD.VecStr(_tbl, 15, s, i - 1) end return out end,
  Rarities = function(s) local n = GD.VecLen(_tbl, 16, s) local out = {} for i = 1, n do out[i] = GD.VecI8(_tbl, 16, s, i - 1) end return out end,
  SpawnPoints = function(s) local n = GD.VecLen(_tbl, 17, s) local out = {} for i = 1, n do out[i] = setmetatable({_row = GD.RecVec(_tbl, 17, s, i - 1)}, WorldPositionMeta) end return out end,
  RewardTiers = function(s) local n = GD.VecLen(_tbl, 18, s) local out = {} for i = 1, n do out[i] = setmetatable({_row = GD.RecVec(_tbl, 18, s, i - 1)}, RewardDefinitionMeta) end return out end,
}

local M = {}
function M.Count() return GD.Count(_tbl) end
function M.ByIndex(i) return setmetatable({_row = GD.ByIndex(_tbl, i)}, RowMeta) end
function M.ByID(id) return setmetatable({_row = GD.ByID(_tbl, id)}, RowMeta) end
return M