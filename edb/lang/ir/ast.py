#
# This source file is part of the EdgeDB open source project.
#
# Copyright 2008-present MagicStack Inc. and the EdgeDB authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


import typing

from edb.lang.common.exceptions import EdgeDBError
from edb.lang.common import ast, compiler, parsing

from edb.lang.schema import modules as s_modules
from edb.lang.schema import name as sn
from edb.lang.schema import objects as so
from edb.lang.schema import pointers as s_pointers
from edb.lang.schema import schema as s_schema
from edb.lang.schema import types as s_types

from edb.lang.edgeql import ast as qlast
from edb.lang.edgeql import functypes as ft

from .pathid import PathId, WeakNamespace  # noqa
from .scopetree import InvalidScopeConfiguration, ScopeTreeNode  # noqa


def new_scope_tree():
    return ScopeTreeNode(fenced=True)


EdgeDBMatchOperator = qlast.EdgeQLMatchOperator
EquivalenceOperator = qlast.EquivalenceOperator
SetOperator = qlast.SetOperator
SetModifier = qlast.SetModifier
Cardinality = qlast.Cardinality

UNION = qlast.UNION

EQUIVALENT = qlast.EQUIVALENT
NEQUIVALENT = qlast.NEQUIVALENT


class ASTError(EdgeDBError):
    pass


class Base(ast.AST):

    __ast_hidden__ = {'context'}

    context: parsing.ParserContext

    def __repr__(self):
        return (
            f'<ir.{self.__class__.__name__} at 0x{id(self):x}>'
        )


class Pointer(Base):

    source: Base
    target: Base
    ptrcls: s_pointers.PointerLike
    direction: s_pointers.PointerDirection
    anchor: typing.Union[str, ast.MetaAST]
    show_as_anchor: typing.Union[str, ast.MetaAST]

    @property
    def is_inbound(self):
        return self.direction == s_pointers.PointerDirection.Inbound


class _BaseTypeRef(Base):
    pass


class TypeRef(_BaseTypeRef):

    maintype: str
    subtypes: typing.List[_BaseTypeRef]


class Set(Base):

    path_id: PathId
    path_scope_id: int
    stype: s_types.Type
    source: Base
    view_source: Base
    expr: Base
    rptr: Pointer
    anchor: typing.Union[str, ast.MetaAST]
    show_as_anchor: typing.Union[str, ast.MetaAST]
    shape: typing.List[Base]

    def __repr__(self):
        return \
            f'<ir.Set \'{self.path_id or self.stype.id}\' at 0x{id(self):x}>'


class Command(Base):
    pass


class Statement(Command):

    expr: Set
    views: typing.Dict[sn.Name, s_types.Type]
    params: typing.Dict[str, s_types.Type]
    cardinality: Cardinality
    stype: s_types.Type
    view_shapes: typing.Dict[so.Object, typing.List[s_pointers.Pointer]]
    schema: s_schema.Schema
    scope_tree: ScopeTreeNode
    scope_map: typing.Dict[Set, str]
    source_map: typing.Dict[s_pointers.Pointer,
                            typing.Tuple[qlast.Expr,
                                         compiler.ContextLevel,
                                         PathId]]


class Expr(Base):
    pass


class EmptySet(Set):
    pass


class BaseConstant(Expr):

    value: str
    stype: s_types.Type

    def __init__(self, *args, stype, **kwargs):
        super().__init__(*args, stype=stype, **kwargs)
        if self.stype is None:
            raise ValueError('cannot create irast.Constant without a type')
        if self.value is None:
            raise ValueError('cannot create irast.Constant without a value')


class StringConstant(BaseConstant):
    pass


class RawStringConstant(BaseConstant):
    pass


class IntegerConstant(BaseConstant):
    pass


class FloatConstant(BaseConstant):
    pass


class BooleanConstant(BaseConstant):
    pass


class BytesConstant(BaseConstant):
    pass


class Parameter(Base):

    name: str
    stype: s_types.Type


class TupleElement(Base):

    name: str
    val: Base


class Tuple(Expr):
    named: bool = False
    elements: typing.List[TupleElement]
    stype: s_types.Type


class Array(Expr):

    elements: typing.List[Base]


class SetOp(Expr):
    left: Set
    right: Set
    op: ast.ops.Operator
    exclusive: bool = False

    left_card: Cardinality
    right_card: Cardinality


class BaseBinOp(Expr):

    left: Base
    right: Base
    op: ast.ops.Operator


class BinOp(BaseBinOp):
    pass


class UnaryOp(Expr):

    expr: Base
    op: ast.ops.Operator


class ExistPred(Expr):

    expr: Set
    negated: bool = False


class DistinctOp(Expr):
    expr: Base


class EquivalenceOp(BaseBinOp):
    pass


class TypeCheckOp(Expr):

    left: Set
    right: typing.Union[TypeRef, Array]
    op: ast.ops.Operator


class IfElseExpr(Expr):

    condition: Set
    if_expr: Set
    else_expr: Set

    if_expr_card: Cardinality
    else_expr_card: Cardinality


class Coalesce(Base):
    left: Set
    right: Set

    right_card: Cardinality


class SortExpr(Base):

    expr: Base
    direction: str
    nones_order: qlast.NonesOrder


class FunctionCall(Expr):

    # Bound function has polymorphic parameters and
    # a polymorphic return type.
    func_polymorphic: bool

    # Bound function's name.
    func_shortname: sn.Name

    # If the bound function is a "FROM SQL" function, this
    # attribute will be set to the name of the SQL function.
    func_sql_function: typing.Optional[str]

    # initial value needed for aggregate function calls to correctly
    # handle empty set
    func_initial_value: Base

    # Bound arguments.
    args: typing.List[Base]

    # Typemods of parameters.  This list corresponds to ".args"
    # (so `zip(args, params_typemods)` is valid.)
    params_typemods: typing.List[ft.TypeModifier]

    # True if the bound function has a variadic parameter and
    # there are no arguments that are bound to it.
    has_empty_variadic: bool = False
    # Set to the type of the variadic parameter of the bound function
    # (or None, if the function has no variadic parameters.)
    variadic_param_type: typing.Optional[s_types.Type]

    # Return type and typemod.  In bodies of polymorphic functions
    # the return type can be polymorphic; in queries the return
    # type will be a concrete schema type.
    stype: s_types.Type
    typemod: ft.TypeModifier

    agg_sort: typing.List[SortExpr]
    agg_filter: Base
    agg_set_modifier: qlast.SetModifier

    partition: typing.List[Base]
    window: bool


class TupleIndirection(Expr):

    expr: Base
    name: str
    path_id: PathId


class IndexIndirection(Expr):

    expr: Base
    index: Base


class SliceIndirection(Expr):

    expr: Base
    start: Base
    stop: Base
    step: Base


class TypeCast(Expr):
    """<Type>Expr"""

    expr: Base
    type: TypeRef


class Stmt(Base):

    name: str
    result: Base
    cardinality: Cardinality
    parent_stmt: Base
    iterator_stmt: Base


class SelectStmt(Stmt):

    where: Base
    orderby: typing.List[SortExpr]
    offset: Base
    limit: Base


class GroupStmt(Stmt):
    subject: Base
    groupby: typing.List[Base]
    result: SelectStmt
    group_path_id: PathId


class MutatingStmt(Stmt):
    subject: Set


class InsertStmt(MutatingStmt):
    pass


class UpdateStmt(MutatingStmt):

    where: Base


class DeleteStmt(MutatingStmt):

    where: Base


class SessionStateCmd(Command):

    modaliases: typing.Dict[typing.Optional[str], s_modules.Module]
    testmode: bool
