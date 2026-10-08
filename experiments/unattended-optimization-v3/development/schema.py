"""Small JSON-schema contract validator for public study tool arguments.

Pure data validation only. It does not execute work or change evidence/state.
Errors identify repair values without silently translating scientific verdicts.
"""
import copy
import re


class RequestArgumentsError(ValueError):
    def __init__(self, tool, issues):
        self.tool, self.issues = tool, issues
        super().__init__('; '.join(item['message'] for item in issues))

    def response(self):
        return {'status':'request_error', 'error':str(self), 'correctable':True,
                'tool':self.tool, 'argument_issues':copy.deepcopy(self.issues),
                'repair':'Correct the listed fields and call the same tool again. No native operation or scientific transition ran for this rejected payload.'}


def validate_arguments(tool, schema, arguments):
    """Validate the declared subset used in these tools; no coercion or defaults."""
    issues=[]
    def problem(field, message, **details):
        issues.append({'field':field,'message':message,**details})
    def visit(value, rule, field):
        types=rule.get('type',[])
        if isinstance(types,str):types=[types]
        checks={'object':lambda x:isinstance(x,dict), 'array':lambda x:isinstance(x,list),
                'string':lambda x:isinstance(x,str), 'boolean':lambda x:type(x) is bool,
                'number':lambda x:type(x) in (int,float), 'integer':lambda x:type(x) is int,
                'null':lambda x:x is None}
        if types and not any(checks[k](value) for k in types):
            problem(field,f'{field} must have type {" or ".join(types)}.',expected_types=types)
            return
        if 'enum' in rule and value not in rule['enum']:
            problem(field,f'{field} must be one of: {", ".join(map(str,rule["enum"]))}.',allowed_values=rule['enum'])
            return
        if isinstance(value,dict):
            props=rule.get('properties',{})
            for name in rule.get('required',[]):
                if name not in value:problem(name,f'Missing required field {name}.',expected_schema=props.get(name,{}))
            for name in value:
                if name not in props:
                    if rule.get('additionalProperties') is False:
                        problem(str(name),f'Unknown field {name}; allowed fields: {", ".join(props)}.',allowed_fields=list(props))
                else:visit(value[name],props[name],name)
        elif isinstance(value,list):
            if len(value)<rule.get('minItems',0):
                problem(field,f'{field} requires at least {rule["minItems"]} item(s).',minimum_items=rule['minItems'])
            for index,item in enumerate(value):visit(item,rule.get('items',{}),f'{field}[{index}]')
        elif isinstance(value,str):
            if len(value)<rule.get('minLength',0) or ('pattern' in rule and not re.search(rule['pattern'],value)):
                problem(field,f'{field} must contain non-whitespace text.',expected_schema=rule)
    visit(arguments,schema,'arguments')
    if issues:raise RequestArgumentsError(tool,issues)
