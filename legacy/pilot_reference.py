"""Legacy pilot reference definitions, extracted by AST without notebook setup.

The original experiment was not re-executed; these definitions support
the 30-record data reconstruction and V1/V2 approval-parity tests.
"""

import copy
import re

schema_fields = ['record_id', 'prefix_title', 'first_name', 'middle_name', 'last_name', 'suffix', 'street_number', 'pre_directional', 'street_name', 'street_type', 'post_directional', 'unit_type', 'unit_number', 'city', 'state', 'postal_code', 'country']
allowed_token_fields = set(schema_fields) - {'record_id'}
PREFIXES = {'mr', 'mrs', 'ms', 'miss', 'dr', 'prof'}
SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}
DIRECTIONALS = {'n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'}
STREET_TYPES = {'street', 'st', 'avenue', 'ave', 'road', 'rd', 'drive', 'dr', 'boulevard', 'blvd', 'lane', 'ln', 'highway', 'hwy', 'court', 'ct'}
UNIT_TYPES = {'apt', 'apartment', 'unit', 'suite', 'ste'}
US_STATES = {'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC', 'PR'}

def clean_token(token):
    return re.sub('^[^\\w]+|[^\\w]+$', '', token).strip()

def get_clue_code(token):
    t = clean_token(token)
    low = t.lower()
    upper = t.upper()
    if low in PREFIXES:
        return 'P'
    if low in SUFFIXES:
        return 'J'
    if low in DIRECTIONALS:
        return 'D'
    if low in STREET_TYPES:
        return 'F'
    if low in UNIT_TYPES:
        return 'S'
    if upper in US_STATES:
        return 'T'
    if t and t[0].isdigit():
        return 'N'
    return 'W'

def mapping_from_fields(fields):
    return {i: field for i, field in enumerate(fields)}

def make_record(record_id, family, raw_record, gold_fields):
    tokens = raw_record.split()
    if len(tokens) != len(gold_fields):
        raise ValueError(f'{record_id}: token count {len(tokens)} does not match gold fields {len(gold_fields)}')
    clue_codes = [get_clue_code(t) for t in tokens]
    token_mask = ''.join(clue_codes)
    return {'record_id': record_id, 'pattern_family': family, 'raw_record': raw_record, 'tokens': tokens, 'clue_codes': clue_codes, 'token_mask': token_mask, 'gold_token_fields': gold_fields, 'gold_mapping': mapping_from_fields(gold_fields)}
A_standard = [('A001', 'Maya Patel 452 Oak Street Conway AR 72032 USA'), ('A002', 'Sara Khan 890 Pine Street Benton AR 72015 USA'), ('A003', 'David Brown 77 Maple Street Bryant AR 72022 USA'), ('A004', 'Emily Johnson 615 Cedar Street Cabot AR 72023 USA'), ('A005', 'Carlos Lopez 921 Lake Street Sherwood AR 72120 USA')]
A_fields = ['first_name', 'last_name', 'street_number', 'street_name', 'street_type', 'city', 'state', 'postal_code', 'country']
B_directional = [('B001', 'Maya Patel 452 N Oak Street Conway AR 72032 USA'), ('B002', 'Sara Khan 890 E Pine Street Benton AR 72015 USA'), ('B003', 'David Brown 77 S Maple Street Bryant AR 72022 USA'), ('B004', 'Emily Johnson 615 W Cedar Street Cabot AR 72023 USA'), ('B005', 'Carlos Lopez 921 NE Lake Street Sherwood AR 72120 USA')]
B_fields = ['first_name', 'last_name', 'street_number', 'pre_directional', 'street_name', 'street_type', 'city', 'state', 'postal_code', 'country']
C_apartment = [('C001', 'Maya Patel 452 Oak Street Apt 7B Conway AR 72032 USA'), ('C002', 'Sara Khan 890 Pine Street Apt 12 Benton AR 72015 USA'), ('C003', 'David Brown 77 Maple Street Apt 3C Bryant AR 72022 USA'), ('C004', 'Emily Johnson 615 Cedar Street Apt 4A Cabot AR 72023 USA'), ('C005', 'Carlos Lopez 921 Lake Street Apt 210 Sherwood AR 72120 USA')]
C_fields = ['first_name', 'last_name', 'street_number', 'street_name', 'street_type', 'unit_type', 'unit_number', 'city', 'state', 'postal_code', 'country']
D_title_middle = [('D001', 'Dr Maya A Patel 452 Oak Street Conway AR 72032 USA'), ('D002', 'Mr John R Smith 125 Main Street Conway AR 72032 USA'), ('D003', 'Ms Emily K Johnson 77 Maple Street Bryant AR 72022 USA'), ('D004', 'Mrs Linda M Anderson 615 Cedar Street Cabot AR 72023 USA'), ('D005', 'Dr Carlos J Lopez 921 Lake Street Sherwood AR 72120 USA')]
D_fields = ['prefix_title', 'first_name', 'middle_name', 'last_name', 'street_number', 'street_name', 'street_type', 'city', 'state', 'postal_code', 'country']
E_suffix = [('E001', 'Maya Patel Jr 452 Oak Street Conway AR 72032 USA'), ('E002', 'Sara Khan II 890 Pine Street Benton AR 72015 USA'), ('E003', 'Robert Wilson II 77 Maple Street Bryant AR 72022 USA'), ('E004', 'Emily Johnson III 615 Cedar Street Cabot AR 72023 USA'), ('E005', 'Carlos Lopez IV 921 Lake Street Sherwood AR 72120 USA')]
E_fields = ['first_name', 'last_name', 'suffix', 'street_number', 'street_name', 'street_type', 'city', 'state', 'postal_code', 'country']
F_two_word_city = [('F001', 'Maya Patel 452 Oak Street Little Rock AR 72204 USA'), ('F002', 'Sara Khan 890 Pine Street Hot Springs AR 71901 USA'), ('F003', 'David Brown 77 Maple Street Pine Bluff AR 71601 USA'), ('F004', 'Emily Johnson 615 Cedar Street Mountain Home AR 72653 USA'), ('F005', 'Carlos Lopez 921 Lake Street El Dorado AR 71730 USA')]
F_fields = ['first_name', 'last_name', 'street_number', 'street_name', 'street_type', 'city', 'city', 'state', 'postal_code', 'country']
known_families = ['A_standard', 'D_title_middle', 'E_suffix']
heldout_families = ['B_directional', 'C_apartment', 'F_two_word_city']

def validate_real_mapping(mapping, tokens, clue_codes):
    errors = []
    expected_positions = set(range(len(tokens)))
    actual_positions = set(mapping.keys())
    if expected_positions != actual_positions:
        missing = expected_positions - actual_positions
        extra = actual_positions - expected_positions
        if missing:
            errors.append(f'Missing positions: {sorted(missing)}')
        if extra:
            errors.append(f'Extra positions: {sorted(extra)}')
    for pos, field in mapping.items():
        if field not in allowed_token_fields:
            errors.append(f'Invalid schema field at position {pos}: {field}')
    allowed_by_code = {'P': {'prefix_title'}, 'J': {'suffix'}, 'D': {'pre_directional', 'post_directional'}, 'F': {'street_type'}, 'S': {'unit_type'}, 'T': {'state'}, 'N': {'street_number', 'unit_number', 'postal_code'}, 'W': allowed_token_fields}
    for pos, code in enumerate(clue_codes):
        if pos not in mapping:
            continue
        field = mapping[pos]
        if field in allowed_token_fields and field not in allowed_by_code[code]:
            errors.append(f"Clue violation: token='{tokens[pos]}', code={code}, field={field}")
    approved = len(errors) == 0
    return (approved, errors)

def make_semantic_swap(gold):
    proposal = copy.deepcopy(gold)
    first_pos = next((pos for pos, field in proposal.items() if field == 'first_name'))
    last_pos = next((pos for pos, field in proposal.items() if field == 'last_name'))
    proposal[first_pos], proposal[last_pos] = (proposal[last_pos], proposal[first_pos])
    return proposal

def make_clue_violation(gold, clue_codes):
    proposal = copy.deepcopy(gold)
    for pos, code in enumerate(clue_codes):
        if code in {'P', 'J', 'D', 'F', 'S', 'T', 'N'}:
            proposal[pos] = 'first_name'
            return proposal
    proposal[0] = 'postal_code'
    return proposal

def make_missing_position(gold):
    proposal = copy.deepcopy(gold)
    proposal.pop(max(proposal.keys()))
    return proposal

def make_invalid_schema(gold):
    proposal = copy.deepcopy(gold)
    proposal[0] = 'favorite_color'
    return proposal

def validate_mapping_v2(mapping, tokens, clue_codes):
    approved, errors = validate_real_mapping(mapping, tokens, clue_codes)
    if not approved:
        return (False, errors)
    errors = list(errors)
    street_number_position = None
    for i, code in enumerate(clue_codes):
        if code == 'N':
            street_number_position = i
            break
    if street_number_position is not None:
        name_positions = list(range(street_number_position))
        core_name_positions = [p for p in name_positions if clue_codes[p] not in {'P', 'J'}]
        if len(core_name_positions) == 2:
            p1, p2 = core_name_positions
            if mapping.get(p1) != 'first_name':
                errors.append(f"Name-position violation: token '{tokens[p1]}' should map to first_name")
            if mapping.get(p2) != 'last_name':
                errors.append(f"Name-position violation: token '{tokens[p2]}' should map to last_name")
        elif len(core_name_positions) == 3:
            p1, p2, p3 = core_name_positions
            expected = {p1: 'first_name', p2: 'middle_name', p3: 'last_name'}
            for position, expected_field in expected.items():
                if mapping.get(position) != expected_field:
                    errors.append(f"Name-position violation: token '{tokens[position]}' should map to {expected_field}")
    return (len(errors) == 0, errors)
