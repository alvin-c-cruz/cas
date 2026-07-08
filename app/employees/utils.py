"""Employee helpers."""


def generate_next_employee_no():
    """Next EMP-#### by numeric suffix (not lexicographic - 'EMP-9999' < 'EMP-10000')."""
    from app.employees.models import Employee
    codes = [e.employee_no for e in Employee.query.filter(Employee.employee_no.like('EMP-%')).all()]
    max_number = 0
    for code in codes:
        try:
            max_number = max(max_number, int(code.split('-', 1)[1]))
        except (ValueError, IndexError):
            continue
    return f'EMP-{max_number + 1:04d}'
