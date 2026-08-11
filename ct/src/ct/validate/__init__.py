"""Validation package for config table export tool.

注意：不在 ``__init__`` 做子模块 re-export——``ct.schema.conventions``
会 import ``ct.validate.errors``，若此处急切 import refs（→ reader →
type_traits → conventions）会构成循环导入。消费者一律直接 import
子模块（``ct.validate.errors`` / ``ct.validate.refs`` / ``ct.validate.types``）。
"""
