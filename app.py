import re
from datetime import date
import bcrypt
from flask import Flask
from flask import request, render_template, redirect, url_for, session, flash
#from werkzeug.security import check_password_hash, generate_password_hash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import pymysql
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.exc import IntegrityError
from decimal import Decimal

app = Flask(__name__)
app.config.from_pyfile('config.py')
db = SQLAlchemy(app)


@app.route("/")
def index():
    try:
        db.session.execute(text('SELECT 1'))  # 这里用 text() 包裹
        return "数据库连接成功!Flask 项目已启动。"
    except Exception as e:
        return f"数据库连接失败：{e}"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # 查询用户账号信息（带上 emp_id）
        conn = db.engine.connect()
        result = conn.execute(
            text("SELECT user_id, password_hash, role, emp_id FROM systemuser WHERE username = :username"),
            {"username": username}
        )
        user = result.fetchone()

        if user and user[1] and bcrypt.checkpw(password.encode('utf-8'), user[1].encode('utf-8')):
            session['user_id'] = user.user_id
            session['role'] = user.role
            session['emp_id'] = user.emp_id

            # 查询员工姓名
            name_result = conn.execute(
                text("SELECT name FROM employee WHERE emp_id = :eid"),
                {"eid": user.emp_id}
            ).fetchone()

            if name_result:
                session['name'] = name_result.name
            else:
                session['name'] = '未知'

            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='用户名或密码错误')

    return render_template('login.html')




@app.route('/dashboard')
def dashboard():
    if 'user_id' in session and 'role' in session:
        return render_template('dashboard.html', role=session['role'])
    else:
        return redirect(url_for('login'))




@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))



@app.route('/employee/info')
def employee_info():
    if 'user_id' not in session or session['role'] != '员工':
        return redirect(url_for('login'))

    conn = db.engine.connect()

    result = conn.execute(text("""
        SELECT 
            e.name, e.gender, e.education, e.phone, e.email,
            e.salary, p.pos_name,
            d.dept_name, m.name AS manager_name, d.function_desc
        FROM systemuser u
        JOIN employee e ON u.emp_id = e.emp_id
        JOIN position p ON e.pos_id = p.pos_id
        JOIN department d ON LEFT(p.pos_id, LENGTH(d.dept_id)) = d.dept_id
        LEFT JOIN employee m ON d.manager_id = m.emp_id
        WHERE u.user_id = :uid
    """), {"uid": session['user_id']})

    row = result.fetchone()

    if not row:
        return "找不到员工信息，请联系管理员"

    info = {
        'name': row[0],
        'gender': row[1],
        'education': row[2],
        'phone': row[3],
        'email': row[4],
        'salary': float(row[5]),
        'pos_name': row[6],
        'dept_name': row[7],
        'manager_name': row[8] or '（未指定）',
        'function_desc': row[9]
    }

    return render_template('employee_info.html', info=info)





@app.route('/leave/request', methods=['GET', 'POST'])
def leave_request():
    if 'user_id' not in session or session['role'] != '员工':
        return redirect(url_for('login'))

    # 获取 emp_id
    conn = db.engine.connect()
    result = conn.execute(text("SELECT emp_id FROM systemuser WHERE user_id = :uid"),
                          {"uid": session['user_id']})
    row = result.fetchone()
    if not row:
        return "找不到员工信息"
    emp_id = row[0]

    if request.method == 'POST':
        leave_type = request.form['leave_type']
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        reason = request.form['reason']

        if end_date <= start_date:
            return render_template('leave_request_form.html', error="结束日期必须晚于开始日期")

        try:
            #用 begin() 保证自动提交
            with db.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO LeaveRequest (emp_id, leave_type, start_date, end_date, request_time, reason)
                    VALUES (:eid, :lt, :sd, :ed, :rt, :rs)
                """), {
                    "eid": emp_id,
                    "lt": leave_type,
                    "sd": start_date,
                    "ed": end_date,
                    "rt": datetime.now(),
                    "rs": reason
                })
            return render_template('leave_request_form.html', message="申请提交成功！")
        except Exception as e:
            import traceback
            print("提交失败：", e)
            traceback.print_exc()
            return render_template('leave_request_form.html', error="提交失败：" + str(e))

    return render_template('leave_request_form.html')

@app.route('/leave/approve', methods=['GET', 'POST'])
def approve_leaves():
    if 'user_id' not in session or session['role'] != '领导':
        return redirect(url_for('login'))

    # 新连接（仅用于获取 reviewer_id）
    with db.engine.connect() as conn:
        result = conn.execute(text("SELECT emp_id FROM systemuser WHERE user_id = :uid"),
                              {"uid": session['user_id']})
        row = result.fetchone()
        if not row:
            return "找不到审批者信息"
        reviewer_id = row[0]

    # POST 提交审批操作
    if request.method == 'POST':
        leave_id = request.form['leave_id']
        action = request.form['action']
        new_status = '已批准' if action == 'approve' else '已拒绝'

        try:
            with db.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE LeaveRequest
                    SET status = :status,
                        reviewer_id = :rid,
                        review_time = :rt
                    WHERE leave_id = :lid
                """), {
                    "status": new_status,
                    "rid": reviewer_id,
                    "rt": datetime.now(),
                    "lid": leave_id
                })
        except Exception as e:
            print("审批失败：", e)

    # 新连接，用于查询当前所有待审批记录
    with db.engine.connect() as conn:
        result = conn.execute(text("""
            SELECT l.leave_id, l.leave_type, l.start_date, l.end_date, l.reason, e.name
            FROM LeaveRequest l
            JOIN employee e ON l.emp_id = e.emp_id
            WHERE l.status = '待审批'
            ORDER BY l.request_time DESC
        """))
        leaves = [
            {
                'leave_id': row[0],
                'leave_type': row[1],
                'start_date': row[2],
                'end_date': row[3],
                'reason': row[4],
                'name': row[5]
            }
            for row in result
        ]

    return render_template('leave_approval.html', leaves=leaves)


@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        old_password = request.form['old_password'].strip()
        new_password = request.form['new_password'].strip()
        confirm_password = request.form['confirm_password'].strip()

        if new_password != confirm_password:
            return render_template('change_password.html', error="两次新密码不一致")

        if not re.fullmatch(r'[A-Za-z0-9]{6,20}', new_password):
            return render_template('change_password.html', error="新密码格式错误，仅允许6-20位字母数字")

        # 获取旧密码哈希
        with db.engine.connect() as conn:
            result = conn.execute(
                text("SELECT password_hash FROM systemuser WHERE user_id = :uid"),
                {"uid": session['user_id']}
            )
            row = result.fetchone()

        if not row or not row[0]:
            return render_template('change_password.html', error="用户信息有误")

        stored_hash = row[0].encode('utf-8')

        if not bcrypt.checkpw(old_password.encode('utf-8'), stored_hash):
            return render_template('change_password.html', error="当前密码不正确")

        # 生成新哈希
        new_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # 写入数据库
        with db.engine.begin() as conn:
            conn.execute(
                text("UPDATE systemuser SET password_hash = :ph, last_password_change = :ts WHERE user_id = :uid"),
                {
                    "ph": new_hash,
                    "ts": datetime.now(),
                    "uid": session['user_id']
                }
            )

        return render_template('change_password.html', message="密码修改成功")

    return render_template('change_password.html')


@app.route('/attendance', methods=['GET', 'POST'])
def attendance():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    emp_id = None
    # 查询 emp_id
    with db.engine.connect() as conn:
        result = conn.execute(
            text("SELECT emp_id FROM systemuser WHERE user_id = :uid"),
            {"uid": session['user_id']}
        ).fetchone()
        if result:
            emp_id = result[0]
        else:
            return "系统错误：找不到员工编号", 500

    if request.method == 'POST':
        today = date.today()

        try:
            with db.engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO Attendance (emp_id, date) VALUES (:eid, :dt)"),
                    {"eid": emp_id, "dt": today}
                )
            return render_template('attendance.html', message="打卡成功！")
        except:
            return render_template('attendance.html', error="今天已打卡")

    return render_template('attendance.html')


@app.route('/attendance/records')
def attendance_records():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # 查询该用户的 emp_id
    with db.engine.connect() as conn:
        result = conn.execute(
            text("SELECT emp_id FROM systemuser WHERE user_id = :uid"),
            {"uid": session['user_id']}
        ).fetchone()

        if not result:
            return "无法找到员工信息", 500

        emp_id = result[0]

        # 查询考勤记录
        records = conn.execute(
            text("SELECT date FROM Attendance WHERE emp_id = :eid ORDER BY date DESC"),
            {"eid": emp_id}
        ).fetchall()

    return render_template("attendance_records.html", records=records)


@app.route('/leave/records')
def leave_records():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    with db.engine.connect() as conn:
        # 获取当前用户的 emp_id
        result = conn.execute(
            text("SELECT emp_id FROM systemuser WHERE user_id = :uid"),
            {"uid": session['user_id']}
        ).fetchone()

        if not result:
            return "找不到用户对应员工编号", 500

        emp_id = result[0]

        # 查询请假记录
        records = conn.execute(
            text("""
                SELECT leave_type, start_date, end_date, request_time, status
                FROM LeaveRequest
                WHERE emp_id = :eid
                ORDER BY request_time DESC
            """),
            {"eid": emp_id}
        ).fetchall()

    return render_template("leave_records.html", records=records)


@app.route('/position_change')
def position_change():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    with db.engine.connect() as conn:
        # 获取当前员工编号
        result = conn.execute(
            text("SELECT emp_id FROM systemuser WHERE user_id = :uid"),
            {"uid": session['user_id']}
        ).fetchone()

        if not result:
            return "找不到对应的员工编号", 500

        emp_id = result[0]

        # 查询变动记录，连接岗位及所属部门
        records = conn.execute(
            text("""
                SELECT pc.change_date,
                       p1.pos_name AS old_pos,
                       d1.dept_name AS old_dept,
                       pc.old_salary,
                       p2.pos_name AS new_pos,
                       d2.dept_name AS new_dept,
                       pc.new_salary
                FROM PositionChange pc
                JOIN Position p1 ON pc.old_pos_id = p1.pos_id
                JOIN Department d1 ON LEFT(p1.pos_id, LENGTH(d1.dept_id)) = d1.dept_id
                JOIN Position p2 ON pc.new_pos_id = p2.pos_id
                JOIN Department d2 ON LEFT(p2.pos_id, LENGTH(d2.dept_id)) = d2.dept_id
                WHERE pc.emp_id = :eid
                ORDER BY pc.change_date DESC
            """),
            {"eid": emp_id}
        ).fetchall()

    return render_template("position_change.html", records=records)





@app.route('/admin/employees')
def admin_employees():
    with db.engine.connect() as conn:
        result = conn.execute(text("""
            SELECT
              e.emp_id,
              e.name,
              e.gender,
              e.education,
              e.phone,
              e.email,
              e.salary,
              p.pos_name,
              d.dept_name
            FROM Employee e
            JOIN Position p ON e.pos_id = p.pos_id
            JOIN Department d ON p.dept_id = d.dept_id
        """)).fetchall()
    return render_template("admin_employees.html", employees=result)





# 岗位/薪资调整：显示所有员工列表
@app.route('/adjust_position/list')
def adjust_position_list():
    if 'role' not in session or session['role'] != '领导':
        flash('权限不足，请重新登录', 'error')
        return redirect(url_for('login'))
    with db.engine.connect() as conn:
        result = conn.execute(text("""
            SELECT e.emp_id, e.name, d.dept_name, p.pos_name, e.salary
            FROM employee e
            JOIN position p ON e.pos_id = p.pos_id
            JOIN department d ON p.dept_id = d.dept_id
            ORDER BY e.emp_id
        """))
        employees = result.fetchall()
    return render_template("adjust_position_list.html", employees=employees)

# 岗位/薪资调整表单页
@app.route('/adjust_position/<emp_id>', methods=['GET', 'POST'])
def adjust_position_form(emp_id):
    if 'role' not in session or session['role'] != '领导':
        flash('权限不足，请重新登录', 'error')
        return redirect(url_for('login'))

    message = None

    with db.engine.connect() as conn:
        # 获取员工基本信息
        emp_result = conn.execute(text("""
            SELECT e.emp_id, e.name, e.salary, p.pos_id, p.pos_name, d.dept_name
            FROM employee e
            JOIN position p ON e.pos_id = p.pos_id
            JOIN department d ON p.dept_id = d.dept_id
            WHERE e.emp_id = :emp_id
        """), {'emp_id': emp_id})
        emp = emp_result.fetchone()

        # 获取所有岗位信息用于选择框
        pos_result = conn.execute(text("""
            SELECT p.pos_id, p.pos_name, d.dept_name, p.min_salary, p.max_salary
            FROM position p
            JOIN department d ON p.dept_id = d.dept_id
        """))
        positions = pos_result.fetchall()

    if request.method == 'POST':
        new_pos_id = request.form.get('new_pos_id')
        new_salary_str = request.form.get('new_salary')

        try:
            new_salary = float(new_salary_str)
        except ValueError:
            message = "❌ 无效的薪资输入。"
            return render_template("adjust_position_form.html", emp=emp, positions=positions, message=message)

        try:
            with db.engine.begin() as conn:
                # 先验证岗位是否存在
                pos_check = conn.execute(text("""
                    SELECT COUNT(*) FROM position WHERE pos_id = :pid
                """), {'pid': new_pos_id}).scalar()
                if pos_check == 0:
                    message = "❌ 所选岗位不存在。"
                    return render_template("adjust_position_form.html", emp=emp, positions=positions, message=message)

                # 插入岗位变动记录（将触发触发器）
                conn.execute(text("""
                    INSERT INTO positionchange (emp_id, change_date, old_pos_id, new_pos_id, old_salary, new_salary)
                    VALUES (:emp_id, NOW(), :old_pos, :new_pos, :old_salary, :new_salary)
                """), {
                    'emp_id': emp.emp_id,
                    'old_pos': emp.pos_id,
                    'new_pos': new_pos_id,
                    'old_salary': Decimal(emp.salary),
                    'new_salary': new_salary
                })

                message = "✅ 岗位和薪资修改成功！"

                # 重新加载更新后的员工信息
                with db.engine.connect() as conn2:
                    emp_result = conn2.execute(text("""
                        SELECT e.emp_id, e.name, e.salary, p.pos_id, p.pos_name, d.dept_name
                        FROM employee e
                        JOIN position p ON e.pos_id = p.pos_id
                        JOIN department d ON p.dept_id = d.dept_id
                        WHERE e.emp_id = :emp_id
                    """), {'emp_id': emp_id})
                    emp = emp_result.fetchone()

        except Exception as e:
            message = f"❌ 修改失败：{str(e).splitlines()[0]}"

    return render_template("adjust_position_form.html", emp=emp, positions=positions, message=message)



@app.route('/add_employee', methods=['GET', 'POST'])
def add_employee():
    if request.method == 'POST':
        # 获取表单数据
        name = request.form['name']
        gender = request.form['gender']
        education = request.form['education']
        phone = request.form['phone']
        email = request.form['email']
        pos_id = request.form['pos_id']
        salary = float(request.form['salary'])

        try:
            # 查询已有员工中最大的emp_id
            conn = db.engine.connect()
            result = conn.execute(text("""
                SELECT emp_id FROM Employee ORDER BY emp_id DESC LIMIT 1
            """)).fetchone()

            # 提取当前最大emp_id中的数字部分并加1
            if result:
                max_emp_id = result[0]  # 获取最大emp_id
                # 提取数字部分并加1
                emp_id_number = int(max_emp_id[3:]) + 1  # 从第四位开始取数字部分并加1
                # 格式化新emp_id
                new_emp_id = f"EMP{emp_id_number:03d}"  # 格式化为EMPxxx
            else:
                new_emp_id = "EMP001"  # 如果没有员工，默认生成EMP001

            # 确保薪资在岗位范围内
            position = conn.execute(text("""
                SELECT min_salary, max_salary FROM Position WHERE pos_id = :pos_id
            """), {"pos_id": pos_id}).fetchone()

            if position:
                min_salary, max_salary = position
                if salary < min_salary or salary > max_salary:
                    return render_template('add_employee.html', error='薪资超出岗位范围', positions=fetch_positions())

            # 插入新员工记录
            conn.execute(text("""
                INSERT INTO Employee (emp_id, name, gender, education, phone, email, pos_id, salary)
                VALUES (:emp_id, :name, :gender, :education, :phone, :email, :pos_id, :salary)
            """), {"emp_id": new_emp_id, "name": name, "gender": gender, "education": education, "phone": phone, "email": email, "pos_id": pos_id, "salary": salary})

            # 提交事务
            conn.commit()
            conn.close()

            return render_template('add_employee.html', success='员工添加成功', positions=fetch_positions())

        except Exception as e:
            return render_template('add_employee.html', error=f"添加失败: {str(e)}", positions=fetch_positions())
    
    # 获取所有岗位
    return render_template('add_employee.html', positions=fetch_positions())

# 查询所有岗位
def fetch_positions():
    conn = db.engine.connect()
    result = conn.execute(text("""
        SELECT pos_id, pos_name, dept_id, min_salary, max_salary
        FROM Position
    """)).fetchall()
    conn.close()

    # 返回岗位数据
    return result


@app.route('/delete_employee/<emp_id>', methods=['POST'])
def delete_employee(emp_id):
    try:
        with db.engine.begin() as conn:
            # 检查该员工是否为任何部门的负责人
            result = conn.execute(text("""
                SELECT COUNT(*) FROM Department WHERE manager_id = :emp_id
            """), {'emp_id': emp_id}).scalar()

            if result > 0:
                flash('❌ 删除失败：该员工是某个部门的负责人，不能删除。', 'error')
                return redirect(url_for('admin_employees'))

            # 删除 SystemUser 表中对应账号
            conn.execute(text("""
                DELETE FROM SystemUser WHERE emp_id = :emp_id
            """), {'emp_id': emp_id})

            # 删除该员工的考勤、请假、岗位变动记录（如果有）
            conn.execute(text("DELETE FROM Attendance WHERE emp_id = :emp_id"), {'emp_id': emp_id})
            conn.execute(text("DELETE FROM LeaveRequest WHERE emp_id = :emp_id"), {'emp_id': emp_id})
            conn.execute(text("DELETE FROM PositionChange WHERE emp_id = :emp_id"), {'emp_id': emp_id})

            # 最后删除 Employee 表中的员工记录
            conn.execute(text("DELETE FROM Employee WHERE emp_id = :emp_id"), {'emp_id': emp_id})

            flash('删除成功', 'success')
    except Exception as e:
        flash(f'删除失败：{str(e)}', 'error')
    return redirect(url_for('admin_employees'))


@app.route('/attendance/view/<emp_id>')
def view_attendance(emp_id):
    if session.get('role') != '领导':
        return redirect(url_for('login'))

    conn = db.engine.connect()
    # 查询员工信息
    emp_info = conn.execute(text("""
        SELECT e.emp_id, e.name, p.pos_name, d.dept_name
        FROM Employee e
        LEFT JOIN Position p ON e.pos_id = p.pos_id
        LEFT JOIN Department d ON p.dept_id = d.dept_id
        WHERE e.emp_id = :emp_id
    """), {"emp_id": emp_id}).fetchone()

    # 查询考勤记录
    records = conn.execute(text("""
        SELECT date
        FROM Attendance
        WHERE emp_id = :emp_id
        ORDER BY date DESC
    """), {"emp_id": emp_id}).fetchall()
    conn.close()

    return render_template("attendance_view.html", emp=emp_info, records=records)


@app.route('/leave/records/<emp_id>')
def view_leave_records(emp_id):
    if session.get('role') != '领导':
        return redirect(url_for('login'))

    conn = db.engine.connect()

    # 查询员工基本信息
    emp = conn.execute(text("""
        SELECT e.emp_id, e.name, p.pos_name, d.dept_name
        FROM Employee e
        LEFT JOIN Position p ON e.pos_id = p.pos_id
        LEFT JOIN Department d ON p.dept_id = d.dept_id
        WHERE e.emp_id = :emp_id
    """), {"emp_id": emp_id}).fetchone()

    # 查询该员工的请假记录
    leaves = conn.execute(text("""
        SELECT l.leave_id, l.leave_type, l.start_date, l.end_date,
               l.request_time, l.status, e.name AS reviewer_name
        FROM LeaveRequest l
        LEFT JOIN Employee e ON l.reviewer_id = e.emp_id
        WHERE l.emp_id = :emp_id
        ORDER BY l.request_time DESC
    """), {"emp_id": emp_id}).fetchall()

    conn.close()
    return render_template("leave_records_view.html", emp=emp, leaves=leaves)


# 选择部门页面
@app.route('/change_manager', methods=['GET'])
def choose_department():
    conn = db.engine.connect()
    departments = conn.execute(text("SELECT dept_id, dept_name FROM Department")).fetchall()
    conn.close()
    return render_template('choose_department.html', departments=departments)


@app.route('/assign_manager/<dept_id>', methods=['GET', 'POST'])
def assign_manager(dept_id):
    conn = db.engine.connect()

    # 获取部门名称和原负责人 ID
    dept_info = conn.execute(text("""
        SELECT d.dept_name, e.name AS manager_name
        FROM Department d
        LEFT JOIN Employee e ON d.manager_id = e.emp_id
        WHERE d.dept_id = :did
    """), {"did": dept_id}).fetchone()

    # 获取该部门所有员工及岗位名
    employees = conn.execute(text("""
        SELECT e.emp_id, e.name, p.pos_name
        FROM Employee e
        JOIN Position p ON e.pos_id = p.pos_id
        WHERE p.dept_id = :did
    """), {"did": dept_id}).fetchall()

    if request.method == 'POST':
        new_manager_id = request.form['manager_id']
        try:
            conn.execute(
                text("UPDATE Department SET manager_id = :mid WHERE dept_id = :did"),
                {"mid": new_manager_id, "did": dept_id}
            )
            flash("部门负责人修改成功", "success")
        except Exception as e:
            flash(f"修改失败: {str(e)}", "error")

    return render_template(
        'assign_manager.html',
        dept_id=dept_id,
        dept_name=dept_info.dept_name,
        current_manager=dept_info.manager_name,
        employees=employees
    )

@app.route('/add_position', methods=['GET', 'POST'])
def add_position():
    with db.engine.begin() as conn:
        departments = conn.execute(text("SELECT dept_id, dept_name FROM Department")).fetchall()

    if request.method == 'POST':
        pos_name = request.form['pos_name']
        dept_id = request.form['dept_id']
        try:
            min_salary = float(request.form['min_salary'])
            max_salary = float(request.form['max_salary'])

            if min_salary > max_salary:
                raise ValueError("最低薪资不能大于最高薪资")

            with db.engine.begin() as conn:
                pos_ids = conn.execute(text(
                    "SELECT pos_id FROM Position WHERE pos_id LIKE :prefix"
                ), {"prefix": f"{dept_id}%"}).fetchall()

                if pos_ids:
                    max_index = max(int(pid[0].replace(dept_id, '')) for pid in pos_ids)
                    new_index = max_index + 1
                else:
                    new_index = 1

                new_pos_id = f"{dept_id}{str(new_index).zfill(3)}"

                conn.execute(text("""
                    INSERT INTO Position (pos_id, pos_name, dept_id, min_salary, max_salary)
                    VALUES (:pos_id, :pos_name, :dept_id, :min_salary, :max_salary)
                """), {
                    'pos_id': new_pos_id,
                    'pos_name': pos_name,
                    'dept_id': dept_id,
                    'min_salary': min_salary,
                    'max_salary': max_salary
                })

            message = f"岗位添加成功！岗位编号为 {new_pos_id}"
            return render_template("add_position.html", departments=departments, message=message)

        except Exception as e:
            return render_template("add_position.html", departments=departments, error=f"添加失败: {str(e)}")

    return render_template("add_position.html", departments=departments)


@app.route('/add_department', methods=['GET', 'POST'])
def add_department():
    message = None
    error = None

    if request.method == 'POST':
        dept_id = request.form['dept_id'].strip().upper()  # 统一为大写
        dept_name = request.form['dept_name'].strip()
        function_desc = request.form['function_desc'].strip()

        if not dept_id.isalpha():
            error = "部门编码只能包含英文字母"
        elif not dept_id or not dept_name:
            error = "部门编号和名称不能为空"
        else:
            try:
                with db.engine.begin() as conn:
                    conn.execute(text("""
                        INSERT INTO Department (dept_id, dept_name, function_desc, manager_id)
                        VALUES (:dept_id, :dept_name, :function_desc, NULL)
                    """), {
                        "dept_id": dept_id,
                        "dept_name": dept_name,
                        "function_desc": function_desc
                    })
                message = f"部门 {dept_name} 添加成功！"
            except Exception as e:
                error = f"添加失败: {str(e)}"

    return render_template("add_department.html", message=message, error=error)


@app.route("/departments")
def view_departments():
    conn = db.engine.connect()

    # 获取所有部门及其经理信息
    departments = conn.execute(text("""
        SELECT d.dept_id, d.dept_name, d.function_desc, e.name AS manager_name
        FROM Department d
        LEFT JOIN Employee e ON d.manager_id = e.emp_id
    """)).fetchall()

    # 为每个部门获取其岗位及对应员工
    dept_info = []
    for dept in departments:
        positions = conn.execute(text("""
            SELECT p.pos_id, p.pos_name
            FROM Position p
            WHERE p.dept_id = :dept_id
        """), {"dept_id": dept.dept_id}).fetchall()

        pos_with_employees = []
        for pos in positions:
            employees = conn.execute(text("""
                SELECT emp_id, name FROM Employee
                WHERE pos_id = :pos_id
            """), {"pos_id": pos.pos_id}).fetchall()

            pos_with_employees.append({
                "pos_id": pos.pos_id,
                "pos_name": pos.pos_name,
                "employees": employees
            })

        dept_info.append({
            "dept_id": dept.dept_id,
            "dept_name": dept.dept_name,
            "function_desc": dept.function_desc,
            "manager_name": dept.manager_name,
            "positions": pos_with_employees
        })

    return render_template("view_departments.html", departments=dept_info)






if __name__ == '__main__': 

    app.run(host="0.0.0.0", port=5000, debug=True)
